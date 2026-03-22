"""Cloudflare R2 storage client for promo folders.

Reads PDFs and metadata from the R2 bucket `milo` under prefix `promo_folders/`.
Uses boto3 S3-compatible API.

Key structure:
    promo_folders/{store_id}/{YYYY-W{WW}}/{name}.pdf
    promo_folders/{store_id}/{YYYY-W{WW}}/metadata.json
"""

import json
import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

R2_BUCKET = "milo"
R2_PREFIX = "promo_folders/"


class R2PromoStorage:
    """Thin wrapper around boto3 for reading promo folders from Cloudflare R2."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            account_id = os.environ.get("R2_ACCOUNT_ID", "")
            access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
            secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
            if not all([account_id, access_key, secret_key]):
                raise RuntimeError(
                    "Missing R2 credentials. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                    "and R2_SECRET_ACCESS_KEY in your .env file."
                )
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="auto",
            )
        return self._client

    def list_store_weeks(self, store_id: str) -> list[str]:
        """List all week directories for a store, sorted alphabetically.

        Returns week names like ["2026-W11", "2026-W12"].
        """
        prefix = f"{R2_PREFIX}{store_id}/"
        response = self.client.list_objects_v2(
            Bucket=R2_BUCKET, Prefix=prefix, Delimiter="/"
        )
        weeks = []
        for cp in response.get("CommonPrefixes", []):
            # cp["Prefix"] looks like "promo_folders/colruyt/2026-W12/"
            week = cp["Prefix"].rstrip("/").rsplit("/", 1)[-1]
            weeks.append(week)
        return sorted(weeks)

    def list_week_pdfs(self, store_id: str, week: str) -> list[str]:
        """List all PDF filenames in a store's week directory."""
        prefix = f"{R2_PREFIX}{store_id}/{week}/"
        response = self.client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix)
        pdfs = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = key.rsplit("/", 1)[-1]
            if filename.lower().endswith(".pdf"):
                pdfs.append(filename)
        return sorted(pdfs)

    def download_pdf(self, store_id: str, week: str, filename: str) -> bytes:
        """Download a PDF from R2 and return its contents as bytes."""
        key = f"{R2_PREFIX}{store_id}/{week}/{filename}"
        logger.info(f"Downloading from R2: {key}")
        response = self.client.get_object(Bucket=R2_BUCKET, Key=key)
        return response["Body"].read()

    def download_metadata(self, store_id: str, week: str) -> Optional[dict]:
        """Download and parse metadata.json for a store's week directory.

        Returns the parsed dict, or None if metadata.json does not exist.
        """
        key = f"{R2_PREFIX}{store_id}/{week}/metadata.json"
        try:
            response = self.client.get_object(Bucket=R2_BUCKET, Key=key)
            return json.loads(response["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
