"""
Wipe all promo data: R2 objects under promo_folders/ + promo_item_images/,
and every row in the promo_items table.

Destructive — requires --yes to actually delete. Use --dry-run to preview counts.

Usage:
    # Preview
    DATABASE_URL=postgresql+asyncpg://... python -m scripts.cleanup_promos --dry-run

    # Execute (non-prod)
    make cleanup-promos

    # Execute (prod)
    make cleanup-promos ENV=production
"""

import argparse
import logging
import os
import sys

import boto3
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

R2_BUCKET = "milo"
R2_PREFIXES = ["promo_folders/", "promo_item_images/"]


def _r2_client():
    account_id = os.environ.get("R2_ACCOUNT_ID", "")
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if not all([account_id, access_key, secret_key]):
        raise RuntimeError(
            "Missing R2 credentials — set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY (see milo-backend/.env)."
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _pg_connection_string() -> str:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    for suffix in ("+asyncpg", "+psycopg2"):
        db_url = db_url.replace(suffix, "")
    return db_url


def count_prefix(s3, prefix: str) -> int:
    paginator = s3.get_paginator("list_objects_v2")
    total = 0
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
        total += len(page.get("Contents", []))
    return total


def wipe_prefix(s3, prefix: str) -> int:
    paginator = s3.get_paginator("list_objects_v2")
    total = 0
    batch: list[dict] = []
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            batch.append({"Key": obj["Key"]})
            if len(batch) == 1000:
                s3.delete_objects(Bucket=R2_BUCKET, Delete={"Objects": batch, "Quiet": True})
                total += len(batch)
                logger.info(f"  {prefix}: deleted {total} so far...")
                batch = []
    if batch:
        s3.delete_objects(Bucket=R2_BUCKET, Delete={"Objects": batch, "Quiet": True})
        total += len(batch)
    return total


def count_promo_items() -> int:
    conn = psycopg2.connect(_pg_connection_string())
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM promo_items")
        (n,) = cur.fetchone()
        cur.close()
        return n
    finally:
        conn.close()


def wipe_promo_items() -> int:
    conn = psycopg2.connect(_pg_connection_string())
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM promo_items")
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return deleted
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Only print counts, delete nothing")
    parser.add_argument("--yes", action="store_true", help="Required to actually delete (no prompt)")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        logger.error("Refusing to delete without --yes. Re-run with --dry-run or --yes.")
        return 2

    mode = "DRY RUN" if args.dry_run else "DELETE"
    db_host = _pg_connection_string().split("@", 1)[-1].split("/", 1)[0]
    logger.info("=" * 60)
    logger.info(f"PROMO CLEANUP [{mode}] — bucket={R2_BUCKET} db={db_host}")
    logger.info("=" * 60)

    s3 = _r2_client()

    r2_counts: dict[str, int] = {}
    for prefix in R2_PREFIXES:
        if args.dry_run:
            n = count_prefix(s3, prefix)
            logger.info(f"R2 {prefix}: {n} objects (would delete)")
        else:
            logger.info(f"Wiping R2 prefix: {prefix}")
            n = wipe_prefix(s3, prefix)
            logger.info(f"  {prefix}: {n} objects deleted")
        r2_counts[prefix] = n

    if args.dry_run:
        n = count_promo_items()
        logger.info(f"promo_items: {n} rows (would delete)")
        db_deleted = n
    else:
        before = count_promo_items()
        logger.info(f"promo_items rows before: {before}")
        db_deleted = wipe_promo_items()
        after = count_promo_items()
        logger.info(f"promo_items rows after: {after}")

    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for p, c in r2_counts.items():
        verb = "would delete" if args.dry_run else "deleted"
        logger.info(f"  R2 {p}: {c} objects {verb}")
    verb = "would delete" if args.dry_run else "deleted"
    logger.info(f"  promo_items: {db_deleted} rows {verb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
