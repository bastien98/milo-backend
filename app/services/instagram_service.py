import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class InstagramService:
    """Instagram Graph API integration for mention detection and reel publishing.

    Requires INSTAGRAM_BUSINESS_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN
    to be configured in environment variables.
    """

    def __init__(self):
        self.account_id = getattr(settings, 'INSTAGRAM_BUSINESS_ACCOUNT_ID', None)
        self.access_token = getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', None)
        self.base_url = "https://graph.facebook.com/v19.0"

    @property
    def is_configured(self) -> bool:
        return bool(self.account_id and self.access_token)

    async def get_mentions(self, since_timestamp: Optional[int] = None) -> list[dict]:
        """Fetch media where @milo_app was tagged/mentioned."""
        if not self.is_configured:
            logger.warning("Instagram API not configured. Skipping mention sync.")
            return []

        params = {
            "fields": "username,timestamp,media_url,media_type",
            "access_token": self.access_token,
        }
        if since_timestamp:
            params["since"] = str(since_timestamp)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/{self.account_id}/tags",
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])

    def extract_handles_from_mentions(self, mentions: list[dict]) -> set[str]:
        """Extract unique Instagram usernames from mention data."""
        handles = set()
        for mention in mentions:
            username = mention.get("username")
            if username:
                handles.add(username.lower())
        return handles

    async def publish_reel(self, video_url: str, caption: str) -> Optional[str]:
        """Publish a video as an Instagram Reel. Returns media_id."""
        if not self.is_configured:
            logger.warning("Instagram API not configured. Skipping reel publish.")
            return None

        async with httpx.AsyncClient() as client:
            # Step 1: Create media container
            create_response = await client.post(
                f"{self.base_url}/{self.account_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
                timeout=60.0,
            )
            create_response.raise_for_status()
            creation_id = create_response.json().get("id")

            if not creation_id:
                raise ValueError("Failed to get creation ID from Instagram")

            # Step 2: Poll for upload completion
            import asyncio
            for _ in range(30):
                status_response = await client.get(
                    f"{self.base_url}/{creation_id}",
                    params={
                        "fields": "status_code",
                        "access_token": self.access_token,
                    },
                    timeout=30.0,
                )
                status_data = status_response.json()
                if status_data.get("status_code") == "FINISHED":
                    break
                if status_data.get("status_code") == "ERROR":
                    raise ValueError(f"Instagram upload failed: {status_data}")
                await asyncio.sleep(2)

            # Step 3: Publish
            publish_response = await client.post(
                f"{self.base_url}/{self.account_id}/media_publish",
                data={
                    "creation_id": creation_id,
                    "access_token": self.access_token,
                },
                timeout=30.0,
            )
            publish_response.raise_for_status()
            return publish_response.json().get("id")
