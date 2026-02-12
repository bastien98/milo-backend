#
# wallet_pass.py
# Pydantic schemas for Wallet Pass creation
#

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class BarcodeFormat(str, Enum):
    QR = "PKBarcodeFormatQR"
    PDF417 = "PKBarcodeFormatPDF417"
    AZTEC = "PKBarcodeFormatAztec"
    CODE128 = "PKBarcodeFormatCode128"


class PassColor(BaseModel):
    red: float = Field(ge=0, le=1)
    green: float = Field(ge=0, le=1)
    blue: float = Field(ge=0, le=1)


class WalletPassCreateRequest(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=100)
    barcode_value: str = Field(..., min_length=1)
    barcode_format: BarcodeFormat = BarcodeFormat.QR
    background_color: PassColor
    foreground_color: PassColor
    label_color: PassColor
    logo_base64: Optional[str] = None  # Base64 encoded PNG


class WalletPassCreateResponse(BaseModel):
    success: bool
    pass_data: Optional[str] = None  # Base64 encoded .pkpass file
    error: Optional[str] = None
