"""Upload scraped promo folder images to Cloudflare R2.

Provides idempotent upload: deletes all existing objects for a store,
then uploads fresh images and metadata.
"""

import json
import logging
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from promo_folders_pipelines.r2_storage import R2PromoStorage, R2_BUCKET, R2_PREFIX
from .scrape import FolderPages

logger = logging.getLogger(__name__)


def get_existing_folder_uuids(r2: R2PromoStorage, store_id: str) -> set[str]:
    """Read all metadata.json files for a store and return their folder_uuids.

    Used for change detection: compare discovered UUIDs against this set
    to determine which folders are new and need Gemini extraction.
    """
    safe_id = store_id.replace(" ", "_")
    prefix = f"{R2_PREFIX}{safe_id}/"
    uuids = set()

    # List all objects to find metadata.json files
    continuation_token = None
    while True:
        kwargs = {"Bucket": R2_BUCKET, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = r2.client.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/metadata.json"):
                try:
                    meta_response = r2.client.get_object(Bucket=R2_BUCKET, Key=key)
                    metadata = json.loads(meta_response["Body"].read())
                    folder_uuid = metadata.get("folder_uuid")
                    if folder_uuid:
                        uuids.add(folder_uuid)
                        logger.debug(f"Found existing folder UUID: {folder_uuid} in {key}")
                except (ClientError, json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to read metadata from {key}: {e}")

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    logger.info(f"Found {len(uuids)} existing folder UUID(s) for '{store_id}' in R2")
    return uuids


def _store_prefix(store_id: str) -> str:
    """Build the R2 key prefix for a store. Uses underscores for path safety."""
    safe_id = store_id.replace(" ", "_")
    return f"{R2_PREFIX}{safe_id}/"


def clear_store(r2: R2PromoStorage, store_id: str) -> int:
    """Delete all existing objects under a store's prefix in R2.

    Returns the number of objects deleted.
    """
    prefix = _store_prefix(store_id)
    logger.info(f"Clearing R2 prefix: {prefix}")

    # List all objects under the prefix
    objects_to_delete = []
    continuation_token = None

    while True:
        kwargs = {"Bucket": R2_BUCKET, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = r2.client.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            objects_to_delete.append({"Key": obj["Key"]})

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    if not objects_to_delete:
        logger.info(f"No existing objects to delete under {prefix}")
        return 0

    # Delete in batches of 1000 (S3/R2 limit)
    deleted = 0
    for i in range(0, len(objects_to_delete), 1000):
        batch = objects_to_delete[i : i + 1000]
        r2.client.delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": batch, "Quiet": True},
        )
        deleted += len(batch)

    logger.info(f"Deleted {deleted} object(s) from {prefix}")
    return deleted


def upload_folder(
    r2: R2PromoStorage,
    store_id: str,
    folder_index: int,
    folder_pages: FolderPages,
    page_images: list[tuple[int, bytes]],
) -> int:
    """Upload a single folder's page images and metadata to R2.

    Args:
        r2: R2 storage client
        store_id: Canonical store ID (e.g., "albert heijn")
        folder_index: 1-based folder index (for multi-folder stores)
        folder_pages: Folder metadata and page info
        page_images: List of (page_number, image_bytes) tuples

    Returns:
        Number of objects uploaded.
    """
    safe_id = store_id.replace(" ", "_")
    folder_prefix = f"{R2_PREFIX}{safe_id}/folder_{folder_index}/"

    uploaded = 0
    folder = folder_pages.folder

    # Upload page images
    for page_num, image_data in page_images:
        key = f"{folder_prefix}page_{page_num:03d}.webp"
        logger.info(f"Uploading {key} ({len(image_data) / 1000:.0f} KB)")
        r2.client.put_object(
            Bucket=R2_BUCKET,
            Key=key,
            Body=image_data,
            ContentType="image/webp",
        )
        uploaded += 1

    # Upload metadata.json
    metadata = {
        "source_url": f"https://www.promopromo.be/nl/{folder.shop_slug}-folder/{folder.uuid}/0",
        "folder_uuid": folder.uuid,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "validity_start": folder.validity_start,
        "validity_end": folder.validity_end,
        "page_count": folder_pages.page_count,
        "image_format": "webp",
    }
    meta_key = f"{folder_prefix}metadata.json"
    r2.client.put_object(
        Bucket=R2_BUCKET,
        Key=meta_key,
        Body=json.dumps(metadata, indent=2).encode(),
        ContentType="application/json",
    )
    uploaded += 1

    logger.info(
        f"Uploaded folder_{folder_index}: {len(page_images)} pages + metadata "
        f"to {folder_prefix}"
    )
    return uploaded
