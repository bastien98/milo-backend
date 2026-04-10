#!/usr/bin/env python3
"""
Bounding box extraction accuracy test across all retailer promo folders.

Downloads page images from R2, asks Gemini to return bounding boxes per item,
crops each product region using Pillow, and writes an HTML report for visual
inspection.

Usage (from milo-backend/):
    # All retailers, 2 pages each
    python -m testbench.test_bbox_extraction

    # Single retailer
    python -m testbench.test_bbox_extraction --store colruyt

    # More pages per retailer
    python -m testbench.test_bbox_extraction --pages 4

    # Skip Gemini call, only download + show pages
    python -m testbench.test_bbox_extraction --download-only

    # Skip image enhancement step (faster, cheaper)
    python -m testbench.test_bbox_extraction --skip-enhance

Output:
    testbench/bbox_test_output/
    ├── colruyt/
    │   ├── page_001_annotated.webp           # page with bbox rectangles drawn
    │   ├── page_001_item_00.webp             # individual crops
    │   ├── page_001_item_00_enhanced.webp    # Gemini-enhanced crop
    │   ├── page_001_item_01.webp
    │   ├── page_001_item_01_enhanced.webp
    │   └── ...
    ├── delhaize/
    │   └── ...
    └── report.html                           # visual report, open in browser
"""

import argparse
import base64
import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed.")
    sys.exit(1)

from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel, Field

from promo_folders_pipelines.r2_storage import R2PromoStorage, R2_BUCKET, R2_PREFIX
from promo_folders_pipelines.scraper.config import list_retailers, get_retailer
from promo_folders_pipelines.stores import load_store_config
from promo_folders_pipelines.prompt_builder import build_system_prompt
from app.core.categories import CATEGORIES_PROMPT_LIST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3-pro-preview"
OUTPUT_DIR = BACKEND_ROOT / "testbench" / "bbox_test_output"

# Padding added around each crop (fraction of page dimension)
CROP_PADDING = 0.01

# Minimum bbox area (fraction of page) — smaller boxes are likely noise
MIN_BBOX_AREA = 0.005

# Colours for drawing bbox rectangles on annotated pages
BBOX_COLOURS = [
    "#FF3B30", "#FF9500", "#FFCC00", "#34C759", "#00C7BE",
    "#30B0C7", "#007AFF", "#5856D6", "#AF52DE", "#FF2D55",
]


# ---------------------------------------------------------------------------
# Gemini schema — existing fields + bounding box
# ---------------------------------------------------------------------------

class _BboxSchema(PydanticBaseModel):
    x_min: float = Field(ge=0.0, le=1.0, description="Left edge, normalized 0-1 (0=left of page)")
    y_min: float = Field(ge=0.0, le=1.0, description="Top edge, normalized 0-1 (0=top of page)")
    x_max: float = Field(ge=0.0, le=1.0, description="Right edge, normalized 0-1 (1=right of page)")
    y_max: float = Field(ge=0.0, le=1.0, description="Bottom edge, normalized 0-1 (1=bottom of page)")


class _PromoItemWithBbox(PydanticBaseModel):
    display_name: str = Field(description="Clean product label, Title Case.")
    display_mechanism: str = Field(description="Standardized promo label (e.g. '1+1 Gratis', '-25%').")
    original_price: float = Field(ge=0, description="Regular price before promo.")
    promo_price: float = Field(ge=0, description="Promo price of ONE unit/pack.")
    page_number: int = Field(ge=1, description="Page number in this batch, 1-indexed.")
    bbox: _BboxSchema = Field(
        description=(
            "Tight bounding box around the ENTIRE product tile on the page — include the "
            "product photo, product name, price labels, and promo badge. "
            "Coordinates are normalized 0-1 relative to the full page image dimensions."
        )
    )


class _PageResultWithBbox(PydanticBaseModel):
    items: list[_PromoItemWithBbox] = Field(description="All promotional items on these pages.")


# ---------------------------------------------------------------------------
# R2 helpers — list and download scraper-uploaded page images
# ---------------------------------------------------------------------------

def list_store_folders(r2: R2PromoStorage, store_id: str) -> list[str]:
    """Return folder prefixes for a store, e.g. ['promo_folders/colruyt/folder_1/']."""
    safe_id = store_id.replace(" ", "_")
    prefix = f"{R2_PREFIX}{safe_id}/"
    response = r2.client.list_objects_v2(
        Bucket=R2_BUCKET, Prefix=prefix, Delimiter="/"
    )
    prefixes = [cp["Prefix"] for cp in response.get("CommonPrefixes", [])]
    logger.info(f"  {store_id}: found {len(prefixes)} folder(s) in R2")
    return sorted(prefixes)


def list_folder_pages(r2: R2PromoStorage, folder_prefix: str) -> list[str]:
    """Return R2 keys for page WebP images under a folder prefix."""
    response = r2.client.list_objects_v2(Bucket=R2_BUCKET, Prefix=folder_prefix)
    keys = [
        obj["Key"]
        for obj in response.get("Contents", [])
        if obj["Key"].endswith(".webp") and "/page_" in obj["Key"]
    ]
    return sorted(keys)


def download_page(r2: R2PromoStorage, key: str) -> bytes:
    response = r2.client.get_object(Bucket=R2_BUCKET, Key=key)
    return response["Body"].read()


# ---------------------------------------------------------------------------
# Gemini extraction with bbox
# ---------------------------------------------------------------------------

BBOX_SYSTEM_PROMPT_SUFFIX = """
## BOUNDING BOX INSTRUCTIONS

For EVERY extracted item, provide a `bbox` field with the TIGHT bounding box of the
complete product tile on the page. The tile typically includes:
- The product photo or illustration
- The product name and variant text
- The price labels (original + promo)
- The promotional badge or sticker

Coordinates are NORMALIZED 0.0 to 1.0 relative to the full page image:
  x_min=0.0 is the LEFT edge of the page
  x_max=1.0 is the RIGHT edge of the page
  y_min=0.0 is the TOP edge of the page
  y_max=1.0 is the BOTTOM edge of the page

Rules:
- bbox MUST contain the entire product tile — do not clip any part of it
- For products that span the full page width, set x_min=0.0, x_max=1.0
- x_min < x_max and y_min < y_max (invalid boxes will be dropped)
- Provide one bbox per item even if the product appears multiple times

VALIDATION: Before outputting each bbox, verify x_min < x_max and y_min < y_max.
"""


GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

ENHANCE_PROMPT = (
    "Edit this product image from a supermarket promotional flyer. "
    "Remove all text, price tags, promotional badges, stickers, logos, and any overlay graphics. "
    "Keep only the physical product itself. "
    "Place the product centered on a clean, solid white background with some padding around it. "
    "Enhance the image quality: sharpen product details, correct colors, and improve resolution. "
    "The result should look like a clean e-commerce product photo on a white background."
)


def extract_with_bbox(
    client: genai.Client,
    page_images: list[tuple[int, bytes]],
    system_prompt: str,
    store_name: str,
) -> list[_PromoItemWithBbox]:
    """Send page images to Gemini and extract items with bounding boxes."""
    parts = []
    for page_num, img_bytes in page_images:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/webp"))
    parts.append(types.Part.from_text(
        text=f"Extract all promotional items with their bounding boxes from these {store_name} pages."
    ))

    full_prompt = system_prompt + BBOX_SYSTEM_PROMPT_SUFFIX

    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=full_prompt,
                    max_output_tokens=16384,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=_PageResultWithBbox,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                ),
            )
            text = response.text
            if not text:
                raise ValueError("Empty response from Gemini")

            cleaned = re.sub(r",\s*([}\]])", r"\1", text)
            data = json.loads(cleaned)
            items = [_PromoItemWithBbox(**item) for item in data.get("items", [])]
            logger.info(f"  Gemini returned {len(items)} items with bboxes")
            return items

        except Exception as e:
            logger.warning(f"  Attempt {attempt} failed: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)

    return []


# ---------------------------------------------------------------------------
# Image processing — draw overlays + crop
# ---------------------------------------------------------------------------

def annotate_page(
    page_bytes: bytes,
    items: list[_PromoItemWithBbox],
) -> bytes:
    """Draw coloured bounding boxes on the page image. Returns WebP bytes."""
    img = Image.open(io.BytesIO(page_bytes)).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")

    for i, item in enumerate(items):
        bbox = item.bbox
        colour = BBOX_COLOURS[i % len(BBOX_COLOURS)]

        px1 = int(bbox.x_min * w)
        py1 = int(bbox.y_min * h)
        px2 = int(bbox.x_max * w)
        py2 = int(bbox.y_max * h)

        # Semi-transparent fill
        draw.rectangle([px1, py1, px2, py2], fill=colour + "30", outline=colour + "CC", width=3)

        # Label background
        label = f"{i+1}. {item.display_name[:30]}"
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        except Exception:
            font = ImageFont.load_default()

        text_bbox = draw.textbbox((px1 + 4, py1 + 4), label, font=font)
        draw.rectangle(text_bbox, fill=colour + "CC")
        draw.text((px1 + 4, py1 + 4), label, fill="white", font=font)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="WEBP", quality=85)
    return out.getvalue()


def crop_item(page_bytes: bytes, bbox: _BboxSchema) -> bytes:
    """Crop product region from page. Returns WebP bytes or empty on failure."""
    img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
    w, h = img.size

    # Apply padding
    pad_x = int(CROP_PADDING * w)
    pad_y = int(CROP_PADDING * h)

    x1 = max(0, int(bbox.x_min * w) - pad_x)
    y1 = max(0, int(bbox.y_min * h) - pad_y)
    x2 = min(w, int(bbox.x_max * w) + pad_x)
    y2 = min(h, int(bbox.y_max * h) + pad_y)

    if x2 <= x1 or y2 <= y1:
        return b""

    crop = img.crop((x1, y1, x2, y2))
    out = io.BytesIO()
    crop.save(out, format="WEBP", quality=90)
    return out.getvalue()


def enhance_image(
    client: genai.Client,
    crop_bytes: bytes,
) -> Optional[bytes]:
    """Send a cropped product image to Gemini for enhancement.

    Uses gemini-3-pro-image-preview to remove text overlays, isolate the
    product on a white background, and enhance quality.
    Returns WebP bytes or None on failure.
    """
    # Skip very small crops
    img = Image.open(io.BytesIO(crop_bytes))
    if img.width < 64 or img.height < 64:
        logger.warning(f"  Skipping enhancement — crop too small ({img.width}x{img.height})")
        return None

    for attempt in range(1, 4):
        try:
            # Send PIL Image directly + text prompt (SDK handles conversion)
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=[ENHANCE_PROMPT, img],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            # Extract image from response parts
            for part in response.parts:
                if part.inline_data is not None:
                    enhanced_img = part.as_image().convert("RGB")
                    out = io.BytesIO()
                    enhanced_img.save(out, format="WEBP", quality=90)
                    return out.getvalue()

            logger.warning(f"  Attempt {attempt}: no image in Gemini response")

        except Exception as e:
            logger.warning(f"  Enhancement attempt {attempt} failed: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)

    return None


def bbox_area(bbox: _BboxSchema) -> float:
    return max(0.0, bbox.x_max - bbox.x_min) * max(0.0, bbox.y_max - bbox.y_min)


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

def _img_tag(path: Path, width: int = 300) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode()
    return f'<img src="data:image/webp;base64,{b64}" width="{width}" style="border-radius:8px;border:1px solid #333">'


def generate_report(
    results: list[dict],
    output_dir: Path,
) -> Path:
    """Generate an HTML report embedding all annotated pages and crops."""
    sections = []

    for store_result in results:
        store_id = store_result["store_id"]
        store_dir = output_dir / store_id
        page_sections = []

        for page_result in store_result["pages"]:
            page_key = page_result["r2_key"]
            page_name = Path(page_key).name
            items = page_result["items"]
            annotated_path = page_result.get("annotated_path")
            crop_paths = page_result.get("crop_paths", [])
            enhanced_paths = page_result.get("enhanced_paths", [])

            crops_html = ""
            for idx, (item, crop_path) in enumerate(zip(items, crop_paths)):
                if crop_path and crop_path.exists():
                    enhanced_path = enhanced_paths[idx] if idx < len(enhanced_paths) else None
                    enhanced_html = ""
                    if enhanced_path and enhanced_path.exists():
                        enhanced_html = f"""
                        <div style="margin-top:6px">
                            <div style="font-size:10px;color:#34C759;margin-bottom:2px">Enhanced:</div>
                            {_img_tag(enhanced_path, 180)}
                        </div>"""

                    crops_html += f"""
                    <div style="display:inline-block;margin:8px;text-align:center;max-width:200px;vertical-align:top">
                        {_img_tag(crop_path, 180)}
                        <div style="font-size:12px;color:#ccc;margin-top:4px">{idx+1}. {item.display_name}</div>
                        <div style="font-size:11px;color:#888">{item.display_mechanism} | €{item.promo_price:.2f}</div>
                        <div style="font-size:10px;color:#666">
                            bbox ({item.bbox.x_min:.2f},{item.bbox.y_min:.2f}) → ({item.bbox.x_max:.2f},{item.bbox.y_max:.2f})
                            area={bbox_area(item.bbox):.3f}
                        </div>{enhanced_html}
                    </div>"""

            annotated_html = ""
            if annotated_path and annotated_path.exists():
                annotated_html = _img_tag(annotated_path, 500)

            page_sections.append(f"""
            <div style="background:#1a1a1a;border-radius:12px;padding:16px;margin-bottom:16px">
                <h3 style="color:#aaa;font-size:14px;margin:0 0 12px 0">{page_name} — {len(items)} items</h3>
                <div style="display:flex;gap:16px;align-items:flex-start">
                    <div style="flex-shrink:0">{annotated_html}</div>
                    <div style="flex:1;overflow-x:auto">{crops_html or '<span style="color:#666">No items extracted</span>'}</div>
                </div>
            </div>""")

        item_count = sum(len(p["items"]) for p in store_result["pages"])
        sections.append(f"""
        <details open>
            <summary style="font-size:20px;font-weight:700;color:white;cursor:pointer;padding:12px 0">
                {store_id.title()} — {len(store_result["pages"])} pages, {item_count} items
            </summary>
            <div style="padding:8px 0">
                {"".join(page_sections)}
            </div>
        </details>
        <hr style="border-color:#333;margin:24px 0">""")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Milo — Bbox Extraction Test</title>
    <style>
        body {{ background: #0d0d0d; color: #eee; font-family: -apple-system, sans-serif; padding: 24px; max-width: 1400px; margin: 0 auto; }}
        summary::-webkit-details-marker {{ color: #34C759; }}
        details[open] > summary {{ color: #34C759; }}
    </style>
</head>
<body>
    <h1>Bbox Extraction Test Report</h1>
    <p style="color:#888">Generated at {time.strftime('%Y-%m-%d %H:%M:%S')} — model: {GEMINI_MODEL}</p>
    <hr style="border-color:#333;margin:16px 0 32px 0">
    {"".join(sections)}
</body>
</html>"""

    report_path = output_dir / "report.html"
    report_path.write_text(html)
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_store(
    key: str,
    r2: R2PromoStorage,
    client: genai.Client,
    max_pages: int,
    download_only: bool,
    skip_enhance: bool,
    output_dir: Path,
) -> dict:
    config = get_retailer(key)
    store_id = config["store_id"]
    store_dir = output_dir / store_id
    store_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing {key} (store_id='{store_id}')")

    # Find page images in R2
    folder_prefixes = list_store_folders(r2, store_id)
    if not folder_prefixes:
        logger.warning(f"  No folders found in R2 for {store_id} — skipping")
        return {"store_id": store_id, "pages": []}

    # Collect page keys across folders, up to max_pages total
    page_keys: list[str] = []
    for prefix in folder_prefixes:
        keys = list_folder_pages(r2, prefix)
        page_keys.extend(keys)
        if len(page_keys) >= max_pages:
            break
    page_keys = page_keys[:max_pages]

    if not page_keys:
        logger.warning(f"  No page images found in R2 for {store_id}")
        return {"store_id": store_id, "pages": []}

    logger.info(f"  Testing {len(page_keys)} page(s): {[Path(k).name for k in page_keys]}")

    store_config = load_store_config(key)
    system_prompt = build_system_prompt(store_config, CATEGORIES_PROMPT_LIST)
    page_results = []

    for page_key in page_keys:
        page_name = Path(page_key).stem  # e.g. "page_001"
        logger.info(f"  Downloading {page_name}...")
        page_bytes = download_page(r2, page_key)
        logger.info(f"  Downloaded {len(page_bytes)/1024:.0f} KB")

        # Derive 1-indexed page number from filename (page_001 → 1)
        try:
            page_num = int(page_name.split("_")[-1])
        except ValueError:
            page_num = 1

        items: list[_PromoItemWithBbox] = []
        if not download_only:
            logger.info(f"  Sending to Gemini ({GEMINI_MODEL})...")
            items = extract_with_bbox(client, [(page_num, page_bytes)], system_prompt, store_id)

            # Filter out invalid bboxes
            valid_items = []
            for item in items:
                b = item.bbox
                if b.x_min >= b.x_max or b.y_min >= b.y_max:
                    logger.warning(f"  Dropping invalid bbox for '{item.display_name}': {b}")
                    continue
                if bbox_area(b) < MIN_BBOX_AREA:
                    logger.warning(f"  Dropping tiny bbox (area={bbox_area(b):.4f}) for '{item.display_name}'")
                    continue
                valid_items.append(item)

            dropped = len(items) - len(valid_items)
            if dropped:
                logger.info(f"  Dropped {dropped} invalid/tiny bbox(es) — {len(valid_items)} valid")
            items = valid_items

        # Annotate page with overlays
        annotated_path = None
        if items:
            annotated_bytes = annotate_page(page_bytes, items)
            annotated_path = store_dir / f"{page_name}_annotated.webp"
            annotated_path.write_bytes(annotated_bytes)
            logger.info(f"  Saved annotated page → {annotated_path.name}")
        else:
            # Save raw page for reference
            annotated_path = store_dir / f"{page_name}_raw.webp"
            annotated_path.write_bytes(page_bytes)

        # Crop individual items and optionally enhance
        crop_paths: list[Optional[Path]] = []
        enhanced_paths: list[Optional[Path]] = []
        for idx, item in enumerate(items):
            crop_bytes = crop_item(page_bytes, item.bbox)
            enhanced_path = None
            if crop_bytes:
                crop_path = store_dir / f"{page_name}_item_{idx:02d}.webp"
                crop_path.write_bytes(crop_bytes)
                crop_paths.append(crop_path)
                logger.info(
                    f"  Crop {idx+1}/{len(items)}: {item.display_name[:40]} "
                    f"bbox=({item.bbox.x_min:.2f},{item.bbox.y_min:.2f},"
                    f"{item.bbox.x_max:.2f},{item.bbox.y_max:.2f}) "
                    f"area={bbox_area(item.bbox):.3f}"
                )

                # Enhance the cropped image with Gemini
                if not skip_enhance and not download_only:
                    logger.info(f"  Enhancing crop {idx+1}/{len(items)}: {item.display_name[:40]}...")
                    enhanced_bytes = enhance_image(client, crop_bytes)
                    if enhanced_bytes:
                        enhanced_path = store_dir / f"{page_name}_item_{idx:02d}_enhanced.webp"
                        enhanced_path.write_bytes(enhanced_bytes)
                        logger.info(f"  Saved enhanced → {enhanced_path.name}")
                    else:
                        logger.warning(f"  Enhancement failed for item {idx+1}")
            else:
                crop_paths.append(None)
            enhanced_paths.append(enhanced_path)

        page_results.append({
            "r2_key": page_key,
            "page_num": page_num,
            "items": items,
            "annotated_path": annotated_path,
            "crop_paths": crop_paths,
            "enhanced_paths": enhanced_paths,
        })

    return {"store_id": store_id, "pages": page_results}


def main():
    parser = argparse.ArgumentParser(
        description="Test Gemini bounding box extraction across retailer promo folders."
    )
    parser.add_argument("--store", help="Single retailer key (e.g. 'colruyt'). Default: all.")
    parser.add_argument("--pages", type=int, default=2, help="Max pages to test per retailer (default: 2).")
    parser.add_argument("--download-only", action="store_true", help="Skip Gemini, only download pages.")
    parser.add_argument("--skip-enhance", action="store_true", help="Skip Gemini image enhancement (faster, cheaper).")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key and not args.download_only:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    r2 = R2PromoStorage()
    client = genai.Client(api_key=gemini_key) if not args.download_only else None

    keys = [args.store] if args.store else list_retailers()
    logger.info(f"Testing {len(keys)} retailer(s): {keys}")
    logger.info(f"Pages per retailer: {args.pages}")
    logger.info(f"Output: {OUTPUT_DIR}")

    all_results = []
    for key in keys:
        try:
            result = process_store(key, r2, client, args.pages, args.download_only, args.skip_enhance, OUTPUT_DIR)
            all_results.append(result)
        except Exception as e:
            logger.error(f"Failed for {key}: {e}", exc_info=True)

    if not args.download_only:
        report_path = generate_report(all_results, OUTPUT_DIR)
        logger.info(f"\n{'='*60}")
        logger.info(f"Report written → {report_path}")
        logger.info(f"Open in browser: file://{report_path}")

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    total_items = 0
    total_pages = 0
    for r in all_results:
        store_pages = len(r["pages"])
        store_items = sum(len(p["items"]) for p in r["pages"])
        total_pages += store_pages
        total_items += store_items
        avg = store_items / store_pages if store_pages else 0
        logger.info(f"  {r['store_id']:20s} {store_pages} pages  {store_items:3d} items  ({avg:.1f} avg/page)")
    logger.info(f"  {'TOTAL':20s} {total_pages} pages  {total_items:3d} items")


if __name__ == "__main__":
    main()
