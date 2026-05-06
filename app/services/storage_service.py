"""S3-compatible object storage service for receipt images.

Uses Railway Buckets (S3-compatible). Gracefully no-ops when
BUCKET_NAME is empty (local dev without a bucket).

Key structure: milo/receipts/{user_id}/{receipt_id}.{ext}
"""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class StorageService:
    """Thin wrapper around boto3 S3 client for receipt image storage."""

    KEY_PREFIX = "milo/receipts"
    CAMPAIGN_KEY_PREFIX = "milo/campaigns"

    def __init__(self):
        self.enabled = bool(settings.AWS_S3_BUCKET_NAME)
        self._client = None

    @property
    def client(self):
        """Lazy-init S3 client (only created when first used)."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.AWS_ENDPOINT_URL,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_DEFAULT_REGION,
            )
        return self._client

    def _build_key(self, user_id: str, receipt_id: str, ext: str) -> str:
        """Build the S3 object key."""
        return f"{self.KEY_PREFIX}/{user_id}/{receipt_id}.{ext}"

    def upload(
        self, user_id: str, receipt_id: str, content: bytes, ext: str
    ) -> Optional[str]:
        """Upload receipt image to S3.

        Returns the storage key on success, None if storage is disabled.
        """
        if not self.enabled:
            return None

        key = self._build_key(user_id, receipt_id, ext)
        content_type_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "pdf": "application/pdf",
        }

        try:
            self.client.put_object(
                Bucket=settings.AWS_S3_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=content_type_map.get(ext, "application/octet-stream"),
            )
            logger.info(f"Uploaded receipt to storage: {key} ({len(content)} bytes)")
            return key
        except ClientError as e:
            logger.error(f"Failed to upload to storage: {key}, error={e}")
            raise

    def upload_campaign_image(
        self,
        campaign_id: str,
        content: bytes,
        ext: str,
        variant: str = "hero",
    ) -> Optional[str]:
        """Upload a brand cashback campaign image variant to S3.

        Variants:
            - "hero": stored at milo/campaigns/{id}.{ext} (used in detail sheet)
            - "thumb": stored at milo/campaigns/{id}_thumb.{ext} (used in grid card)

        Returns the storage key on success, None if storage is disabled.
        """
        if not self.enabled:
            return None

        suffix = "_thumb" if variant == "thumb" else ""
        key = f"{self.CAMPAIGN_KEY_PREFIX}/{campaign_id}{suffix}.{ext}"
        content_type_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }

        try:
            self.client.put_object(
                Bucket=settings.AWS_S3_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=content_type_map.get(ext, "application/octet-stream"),
            )
            logger.info(
                f"Uploaded campaign image ({variant}): {key} ({len(content)} bytes)"
            )
            return key
        except ClientError as e:
            logger.error(f"Failed to upload campaign image: {key}, error={e}")
            raise

    def upload_brand_logo(
        self,
        campaign_id: str,
        content: bytes,
        ext: str,
    ) -> Optional[str]:
        """Upload a campaign's brand logo to S3.

        Stored at milo/campaigns/{id}_brand_logo.{ext}. Single variant —
        unlike the product image, no thumb is generated since logos are
        already small and aspect ratio must be preserved (wordmarks).
        """
        if not self.enabled:
            return None

        key = f"{self.CAMPAIGN_KEY_PREFIX}/{campaign_id}_brand_logo.{ext}"
        content_type_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }

        try:
            self.client.put_object(
                Bucket=settings.AWS_S3_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=content_type_map.get(ext, "application/octet-stream"),
            )
            logger.info(
                f"Uploaded campaign brand logo: {key} ({len(content)} bytes)"
            )
            return key
        except ClientError as e:
            logger.error(f"Failed to upload brand logo: {key}, error={e}")
            raise

    def generate_presigned_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """Generate a presigned URL for reading an object.

        Args:
            key: The S3 object key.
            expires: URL expiry in seconds (default 1 hour).

        Returns:
            Presigned URL string, or None if storage is disabled.
        """
        if not self.enabled:
            return None

        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.AWS_S3_BUCKET_NAME, "Key": key},
                ExpiresIn=expires,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {key}, error={e}")
            raise

    def download(self, key: str) -> Optional[bytes]:
        """Download an object's content from S3.

        Returns:
            File content as bytes, or None if storage is disabled.
        """
        if not self.enabled:
            return None

        try:
            response = self.client.get_object(
                Bucket=settings.AWS_S3_BUCKET_NAME, Key=key
            )
            return response["Body"].read()
        except ClientError as e:
            logger.error(f"Failed to download from storage: {key}, error={e}")
            raise

    def delete(self, key: str) -> None:
        """Delete a single object from S3."""
        if not self.enabled or not key:
            return

        try:
            self.client.delete_object(
                Bucket=settings.AWS_S3_BUCKET_NAME, Key=key
            )
            logger.info(f"Deleted from storage: {key}")
        except ClientError as e:
            logger.warning(f"Failed to delete from storage: {key}, error={e}")

    def delete_user_files(self, user_id: str) -> int:
        """Delete all receipt files for a user (GDPR compliance).

        Returns the number of objects deleted.
        """
        if not self.enabled:
            return 0

        prefix = f"{self.KEY_PREFIX}/{user_id}/"
        deleted_count = 0

        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=settings.AWS_S3_BUCKET_NAME, Prefix=prefix
            ):
                objects = page.get("Contents", [])
                if not objects:
                    continue

                response = self.client.delete_objects(
                    Bucket=settings.AWS_S3_BUCKET_NAME,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
                deleted_count += len(response.get("Deleted", []))

                for error in response.get("Errors", []):
                    logger.error(
                        f"Failed to delete {error['Key']}: {error.get('Message')}"
                    )

            logger.info(
                f"GDPR cleanup: deleted {deleted_count} files for user {user_id}"
            )
            return deleted_count
        except ClientError as e:
            logger.error(
                f"Failed GDPR file cleanup for user {user_id}: {e}"
            )
            raise
