#!/usr/bin/env python3
"""Set or delete a manual bbox override.

The override wins over the extractor's output on every future re-ingest of
(promo_folder_url, page_number, display_name) — one-shot manual fix that sticks.

Usage (from milo-backend/):
    # Set an override on non-prod
    python3 -m promo_folders_pipelines.set_bbox_override \\
        --folder-url "https://www.carrefour.be/..." \\
        --page 7 \\
        --name "Rode paprika" \\
        --tile 0.12,0.18,0.47,0.52 \\
        --note "original bbox hugged wrong neighbor"

    # Also pin the product-only bbox (defaults to tile if omitted)
    python3 -m promo_folders_pipelines.set_bbox_override \\
        --folder-url ... --page 7 --name "Rode paprika" \\
        --tile 0.12,0.18,0.47,0.52 \\
        --bbox 0.15,0.21,0.44,0.49

    # Delete an override
    python3 -m promo_folders_pipelines.set_bbox_override \\
        --folder-url ... --page 7 --name "Rode paprika" --delete

    # Target production (default is non-prod)
    ... --env prod
"""

import argparse
import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed. Run with the venv Python.")
    sys.exit(1)

from promo_folders_pipelines.cache_refresh import notify_folders_cache_refresh
from promo_folders_pipelines.pipeline import (
    _crop_from_normalized_bbox,
    _get_pg_connection_string,
    _normalize_override_name,
    _pad_to_square,
    _resize_to_max,
)
from promo_folders_pipelines.r2_storage import R2_BUCKET, R2_PREFIX, R2PromoStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _find_folder_page_key(r2: R2PromoStorage, source_retailer: str, folder_url: str, page: int) -> str | None:
    """Resolve the R2 key for a folder's page image by matching source_url in metadata.json.

    Returns `promo_folders/{safe_id}/folder_N/page_{page:03d}.webp` or None if not found.
    """
    safe_id = source_retailer.replace(" ", "_")
    prefix = f"{R2_PREFIX}{safe_id}/"
    try:
        resp = r2.client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix, Delimiter="/")
    except Exception as e:
        logger.warning(f"Failed to list R2 prefix {prefix}: {e}")
        return None
    for cp in resp.get("CommonPrefixes", []):
        folder_prefix = cp["Prefix"]
        try:
            meta = r2.client.get_object(Bucket=R2_BUCKET, Key=f"{folder_prefix}metadata.json")
            import json
            data = json.loads(meta["Body"].read())
        except Exception:
            continue
        if data.get("source_url") == folder_url:
            return f"{folder_prefix}page_{page:03d}.webp"
    return None


def _recrop_item_images(
    conn,
    folder_url: str,
    page: int,
    name_norm: str,
) -> int:
    """Re-crop and re-upload thumb/medium/tile for items matching the override triple.

    Uses the bbox/tile_bbox already written to `promo_items` (i.e. the override coords,
    since the UPDATE ran just before this). Returns the number of items re-cropped.
    """
    from io import BytesIO
    from PIL import Image

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, source_retailer,
               bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
               tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max
          FROM promo_items
         WHERE promo_folder_url = %s
           AND page_number = %s
           AND LOWER(TRIM(display_name)) = %s
        """,
        (folder_url, page, name_norm),
    )
    rows = cur.fetchall()
    cur.close()
    if not rows:
        logger.warning("No promo_items row to re-crop")
        return 0

    r2 = R2PromoStorage()
    page_key = _find_folder_page_key(r2, rows[0][1], folder_url, page)
    if not page_key:
        logger.warning(f"Could not resolve page image in R2 for p{page} of {folder_url}")
        return 0
    try:
        page_obj = r2.client.get_object(Bucket=R2_BUCKET, Key=page_key)
        page_img = Image.open(BytesIO(page_obj["Body"].read())).convert("RGB")
    except Exception as e:
        logger.warning(f"Failed to fetch page image {page_key}: {e}")
        return 0

    recropped = 0
    for row in rows:
        (record_id, store_id,
         bx0, by0, bx1, by1,
         tx0, ty0, tx1, ty1) = row

        base_key = f"promo_item_images/{store_id}/{record_id}"

        # Product crop → thumb.webp (200px) + medium.webp (400px), padded to square
        if None not in (bx0, by0, bx1, by1):
            product = _crop_from_normalized_bbox(
                page_img, {"x_min": bx0, "y_min": by0, "x_max": bx1, "y_max": by1}
            )
            if product is not None:
                product = _pad_to_square(product)
                for size, suffix in ((200, "thumb"), (400, "medium")):
                    resized = _resize_to_max(product, size)
                    buf = BytesIO()
                    resized.save(buf, format="WEBP", quality=85)
                    r2.upload_image(f"{base_key}/{suffix}.webp", buf.getvalue())

        # Tile crop → tile.webp (800px), natural aspect
        if None not in (tx0, ty0, tx1, ty1):
            tile = _crop_from_normalized_bbox(
                page_img, {"x_min": tx0, "y_min": ty0, "x_max": tx1, "y_max": ty1}
            )
            if tile is not None:
                resized_tile = _resize_to_max(tile, 800)
                buf = BytesIO()
                resized_tile.save(buf, format="WEBP", quality=85)
                r2.upload_image(f"{base_key}/tile.webp", buf.getvalue())

        logger.info(f"Re-cropped images for {record_id} ({store_id})")
        recropped += 1

    return recropped


def _parse_quad(text: str, label: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise SystemExit(f"--{label} must be 4 comma-separated floats, got {text!r}")
    try:
        x_min, y_min, x_max, y_max = (float(p) for p in parts)
    except ValueError:
        raise SystemExit(f"--{label} values must be floats, got {text!r}")
    for v in (x_min, y_min, x_max, y_max):
        if not 0.0 <= v <= 1.0:
            raise SystemExit(f"--{label} coords must be in [0, 1], got {text!r}")
    if x_min >= x_max or y_min >= y_max:
        raise SystemExit(f"--{label} must satisfy x_min<x_max and y_min<y_max, got {text!r}")
    return x_min, y_min, x_max, y_max


def main() -> None:
    parser = argparse.ArgumentParser(description="Set or delete a manual promo bbox override.")
    parser.add_argument("--folder-url", required=True, help="Exact promo_folder_url the item lives under")
    parser.add_argument("--page", type=int, required=True, help="1-indexed page number")
    parser.add_argument("--name", required=True, help="display_name of the item (case-insensitive match)")
    parser.add_argument(
        "--tile",
        help="tile_bbox as 'x_min,y_min,x_max,y_max' (0-1 floats). Required unless --delete.",
    )
    parser.add_argument(
        "--bbox",
        help="Optional product-only bbox 'x_min,y_min,x_max,y_max'. Defaults to --tile when omitted.",
    )
    parser.add_argument("--note", help="Optional free-text note for why the override was added")
    parser.add_argument("--delete", action="store_true", help="Remove the override row instead of upserting")
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Only update DB rows; skip re-cropping and re-uploading item images to R2",
    )
    parser.add_argument("--env", choices=["prod", "non-prod"], default="non-prod")
    args = parser.parse_args()

    # Env selection mirrors ingest.py
    if args.env == "non-prod":
        nonprod_url = os.environ.get("DATABASE_URL_NONPROD", "")
        if not nonprod_url:
            parser.error("DATABASE_URL_NONPROD not set in .env")
        os.environ["DATABASE_URL"] = nonprod_url
        logger.info("Targeting NON-PROD database")
    else:
        logger.info("Targeting PRODUCTION database")

    import psycopg2

    name_norm = _normalize_override_name(args.name)
    if not name_norm:
        parser.error("--name must not be empty after normalization")

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        if args.delete:
            cur.execute(
                "DELETE FROM promo_item_bbox_overrides "
                "WHERE promo_folder_url = %s AND page_number = %s AND display_name_normalized = %s",
                (args.folder_url, args.page, name_norm),
            )
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            if deleted:
                logger.info(f"Deleted override for p{args.page} '{args.name}'")
            else:
                logger.warning(f"No matching override found for p{args.page} '{args.name}'")
            # Fall through to cache refresh so the API reflects the removal
        else:
            if not args.tile:
                parser.error("--tile is required unless --delete is used")
            tile = _parse_quad(args.tile, "tile")
            bbox = _parse_quad(args.bbox, "bbox") if args.bbox else None

            cur.execute(
                """
                INSERT INTO promo_item_bbox_overrides (
                    promo_folder_url, page_number, display_name_normalized,
                    tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max,
                    bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
                    note
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT uq_promo_item_bbox_overrides_folder_page_name
                DO UPDATE SET
                    tile_bbox_x_min = EXCLUDED.tile_bbox_x_min,
                    tile_bbox_y_min = EXCLUDED.tile_bbox_y_min,
                    tile_bbox_x_max = EXCLUDED.tile_bbox_x_max,
                    tile_bbox_y_max = EXCLUDED.tile_bbox_y_max,
                    bbox_x_min = EXCLUDED.bbox_x_min,
                    bbox_y_min = EXCLUDED.bbox_y_min,
                    bbox_x_max = EXCLUDED.bbox_x_max,
                    bbox_y_max = EXCLUDED.bbox_y_max,
                    note = EXCLUDED.note
                """,
                (
                    args.folder_url,
                    args.page,
                    name_norm,
                    tile[0], tile[1], tile[2], tile[3],
                    bbox[0] if bbox else None,
                    bbox[1] if bbox else None,
                    bbox[2] if bbox else None,
                    bbox[3] if bbox else None,
                    args.note,
                ),
            )
            conn.commit()
            cur.close()
            logger.info(
                f"Upserted override: p{args.page} '{args.name}' "
                f"tile={tile} bbox={bbox or 'tile'}"
            )

        # Apply the override to existing promo_items rows so the fix shows up
        # immediately without a full re-ingest. Matches the same triple.
        cur = conn.cursor()
        if args.delete:
            # Nothing to overwrite — the row is already live with the extractor's coords.
            pass
        else:
            applied_bbox = bbox if bbox else tile
            cur.execute(
                """
                UPDATE promo_items
                   SET tile_bbox_x_min = %s,
                       tile_bbox_y_min = %s,
                       tile_bbox_x_max = %s,
                       tile_bbox_y_max = %s,
                       bbox_x_min = %s,
                       bbox_y_min = %s,
                       bbox_x_max = %s,
                       bbox_y_max = %s
                 WHERE promo_folder_url = %s
                   AND page_number = %s
                   AND LOWER(TRIM(display_name)) = %s
                """,
                (
                    tile[0], tile[1], tile[2], tile[3],
                    applied_bbox[0], applied_bbox[1], applied_bbox[2], applied_bbox[3],
                    args.folder_url,
                    args.page,
                    name_norm,
                ),
            )
            updated = cur.rowcount
            conn.commit()
            cur.close()
            logger.info(f"Patched {updated} live promo_items row(s) with the new bbox")

        # Re-crop and re-upload item images (thumb/medium/tile) from the page image
        # so the iOS product card, detail view, and carousels reflect the new bbox.
        if args.delete:
            logger.warning(
                "Override deleted — cached item images still reflect the prior bbox. "
                "Re-ingest the folder to regenerate them from the extractor's output."
            )
        elif args.skip_images:
            logger.info("--skip-images set: not re-cropping item images")
        else:
            n = _recrop_item_images(conn, args.folder_url, args.page, name_norm)
            logger.info(f"Re-cropped {n} item(s) and uploaded new thumb/medium/tile to R2")
    finally:
        conn.close()

    # Invalidate the API folder cache so the iOS viewer picks up the corrected hotspot.
    notify_folders_cache_refresh(args.env)


if __name__ == "__main__":
    main()
