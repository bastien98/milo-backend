import base64
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import httpx

from app.core.exceptions import VeryfiAPIError
from app.config import get_settings

settings = get_settings()


@dataclass
class VeryfiLineItem:
    """Represents a line item extracted by Veryfi."""
    description: str
    total: Optional[float]
    quantity: Optional[float]
    price: Optional[float]
    type: Optional[str]  # e.g., "food", "alcohol", "product"
    sku: Optional[str]


@dataclass
class VeryfiExtractionResult:
    """Represents the extraction result from Veryfi."""
    vendor_name: Optional[str]
    date: Optional[date]
    total: Optional[float]
    subtotal: Optional[float]
    tax: Optional[float]
    line_items: List[VeryfiLineItem]
    currency_code: Optional[str]
    ocr_text: Optional[str]
    is_duplicate: bool = False
    duplicate_score: Optional[float] = None  # Similarity score (0.0-1.0)


class VeryfiService:
    """Veryfi API integration for receipt OCR extraction."""

    BASE_URL = "https://api.veryfi.com/api/v8/partner/documents"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.client_id = client_id or settings.VERYFI_CLIENT_ID
        self.client_secret = client_secret or settings.VERYFI_CLIENT_SECRET
        self.username = username or settings.VERYFI_USERNAME
        self.api_key = api_key or settings.VERYFI_API_KEY

        if not all([self.client_id, self.username, self.api_key]):
            raise ValueError("Veryfi API credentials not configured")

    def _get_headers(self) -> dict:
        """Get authentication headers for Veryfi API."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CLIENT-ID": self.client_id,
            "AUTHORIZATION": f"apikey {self.username}:{self.api_key}",
        }

    async def extract_receipt_data(
        self, file_content: bytes, filename: str = "receipt.jpg"
    ) -> VeryfiExtractionResult:
        """
        Extract structured data from receipt using Veryfi API.

        Args:
            file_content: Raw bytes of the receipt image/PDF
            filename: Original filename to help determine file type

        Returns:
            VeryfiExtractionResult with extracted data
        """
        try:
            # Encode file as base64
            base64_data = base64.standard_b64encode(file_content).decode("utf-8")

            # Prepare request payload
            payload = {
                "file_data": base64_data,
                "file_name": filename,
                "auto_delete": True,  # Delete from Veryfi after processing
                "boost_mode": False,  # Enable data enrichment
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.BASE_URL,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 401:
                    raise VeryfiAPIError(
                        "Veryfi API authentication failed - invalid credentials",
                        details={"error_type": "authentication"},
                    )
                elif response.status_code == 429:
                    raise VeryfiAPIError(
                        "Veryfi API rate limit exceeded - please retry later",
                        details={"error_type": "rate_limit"},
                    )
                elif response.status_code >= 400:
                    raise VeryfiAPIError(
                        f"Veryfi API error (status {response.status_code})",
                        details={
                            "error_type": "api_error",
                            "status_code": response.status_code,
                            "response": response.text[:500],
                        },
                    )

                data = response.json()
                return self._parse_response(data)

        except httpx.TimeoutException as e:
            raise VeryfiAPIError(
                "Veryfi API request timed out",
                details={"error_type": "timeout"},
            )
        except httpx.RequestError as e:
            raise VeryfiAPIError(
                "Failed to connect to Veryfi API",
                details={"error_type": "connection", "error": str(e)},
            )
        except VeryfiAPIError:
            raise
        except Exception as e:
            raise VeryfiAPIError(
                f"Veryfi extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _parse_response(self, data: dict) -> VeryfiExtractionResult:
        """Parse Veryfi API response into structured result."""
        # Parse line items
        line_items = []
        for item in data.get("line_items", []):
            line_items.append(
                VeryfiLineItem(
                    description=item.get("description") or item.get("text", "Unknown Item"),
                    total=item.get("total"),
                    quantity=item.get("quantity"),
                    price=item.get("price"),
                    type=item.get("type"),
                    sku=item.get("sku"),
                )
            )

        # Parse date
        receipt_date = None
        date_str = data.get("date")
        if date_str:
            try:
                # Veryfi returns date in ISO format
                receipt_date = date.fromisoformat(date_str.split("T")[0])
            except (ValueError, AttributeError):
                pass

        # Get vendor name from nested structure or direct field
        vendor_name = None
        if data.get("vendor"):
            if isinstance(data["vendor"], dict):
                vendor_name = data["vendor"].get("name")
            else:
                vendor_name = data.get("vendor")
        if not vendor_name:
            vendor_name = data.get("vendor_name")

        # Veryfi duplicate detection - only provides boolean flag, no similarity score
        is_duplicate = data.get("is_duplicate", False)
        original_doc_id = data.get("duplicate_of")  # Integer ID of original document

        # Note: Veryfi doesn't provide a similarity score, only boolean is_duplicate
        duplicate_score = None

        return VeryfiExtractionResult(
            vendor_name=vendor_name,
            date=receipt_date,
            total=data.get("total"),
            subtotal=data.get("subtotal"),
            tax=data.get("tax"),
            line_items=line_items,
            currency_code=data.get("currency_code"),
            ocr_text=data.get("ocr_text"),
            is_duplicate=is_duplicate,
            duplicate_score=duplicate_score,
        )
