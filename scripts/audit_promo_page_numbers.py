"""Audit promo_items: page_number, bbox coverage, and folder URL distribution."""

import os
import sys

import psycopg2


def _pg_connection_string() -> str:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    for suffix in ("+asyncpg", "+psycopg2"):
        db_url = db_url.replace(suffix, "")
    return db_url


def main() -> None:
    conn = psycopg2.connect(_pg_connection_string())
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE page_number IS NULL)       AS null_page,
              COUNT(*) FILTER (WHERE promo_folder_url IS NULL)  AS null_folder_url,
              COUNT(*) FILTER (WHERE tile_bbox_x_min IS NULL)   AS null_bbox,
              COUNT(*) FILTER (WHERE validity_end < CURRENT_DATE) AS expired
            FROM promo_items
            """
        )
        total, null_page, null_url, null_bbox, expired = cur.fetchone()
        print(f"TOTAL: {total}")
        print(f"  NULL page_number:     {null_page}")
        print(f"  NULL promo_folder_url:{null_url}")
        print(f"  NULL tile_bbox_x_min: {null_bbox}   (items filtered out of hotspots)")
        print(f"  expired:              {expired}")
        print()

        print("By retailer:")
        cur.execute(
            """
            SELECT source_retailer,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE page_number IS NULL)      AS null_page,
                   COUNT(*) FILTER (WHERE promo_folder_url IS NULL) AS null_url,
                   COUNT(*) FILTER (WHERE tile_bbox_x_min IS NULL)  AS null_bbox,
                   MIN(page_number) AS min_page,
                   MAX(page_number) AS max_page
            FROM promo_items
            WHERE validity_end >= CURRENT_DATE
            GROUP BY source_retailer
            ORDER BY total DESC
            """
        )
        print(f"  {'retailer':<18} {'total':>6} {'∅page':>6} {'∅url':>6} {'∅bbox':>6} {'pages':>10}")
        for retailer, t, np_, nu, nb, mn, mx in cur.fetchall():
            pg = f"{mn}-{mx}" if mn is not None else "-"
            print(f"  {retailer:<18} {t:>6} {np_:>6} {nu:>6} {nb:>6} {pg:>10}")
        print()

        print("Active promo_folder_url values (retailer | url | n_items | page range):")
        cur.execute(
            """
            SELECT source_retailer, promo_folder_url,
                   COUNT(*)             AS n,
                   MIN(page_number)     AS min_p,
                   MAX(page_number)     AS max_p,
                   COUNT(*) FILTER (WHERE tile_bbox_x_min IS NULL) AS no_bbox
            FROM promo_items
            WHERE validity_end >= CURRENT_DATE
            GROUP BY source_retailer, promo_folder_url
            ORDER BY source_retailer, n DESC
            """
        )
        for retailer, url, n, mn, mx, nb in cur.fetchall():
            url_short = (url[:70] + "…") if url and len(url) > 70 else (url or "<NULL>")
            print(f"  [{retailer}] {url_short}")
            print(f"       {n} items, pages {mn}-{mx}, {nb} without bbox")

        cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
