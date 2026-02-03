#
# wallet_pass_service.py
# Service for creating and signing Apple Wallet passes
#

import json
import hashlib
import zipfile
import base64
from io import BytesIO
from typing import Optional
from datetime import datetime
import uuid

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs7

from app.schemas.wallet_pass import WalletPassCreateRequest, PassColor
from app.config import get_settings


class WalletPassService:
    """Service for creating Apple Wallet passes."""

    def __init__(self):
        settings = get_settings()
        self.pass_type_id = settings.WALLET_PASS_TYPE_ID
        self.team_id = settings.WALLET_TEAM_ID
        self.cert_base64 = settings.WALLET_CERT_BASE64
        self.cert_password = settings.WALLET_CERT_PASSWORD
        self.wwdr_cert_base64 = settings.WALLET_WWDR_CERT_BASE64

    def _color_to_rgb_string(self, color: PassColor) -> str:
        """Convert color to RGB string format."""
        r = int(color.red * 255)
        g = int(color.green * 255)
        b = int(color.blue * 255)
        return f"rgb({r}, {g}, {b})"

    def _create_pass_json(self, request: WalletPassCreateRequest, serial_number: str) -> dict:
        """Create the pass.json structure."""
        pass_json = {
            "formatVersion": 1,
            "passTypeIdentifier": self.pass_type_id,
            "serialNumber": serial_number,
            "teamIdentifier": self.team_id,
            "organizationName": request.store_name,
            "description": f"{request.store_name} Loyalty Card",
            "backgroundColor": self._color_to_rgb_string(request.background_color),
            "foregroundColor": self._color_to_rgb_string(request.foreground_color),
            "labelColor": self._color_to_rgb_string(request.label_color),
            "logoText": request.store_name,
            "storeCard": {
                "headerFields": [],
                "primaryFields": [
                    {
                        "key": "member",
                        "label": "MEMBER",
                        "value": request.member_number if request.member_number else request.store_name
                    }
                ],
                "secondaryFields": [],
                "auxiliaryFields": [],
                "backFields": [
                    {
                        "key": "created",
                        "label": "Created with",
                        "value": "Scandalicious App"
                    },
                    {
                        "key": "date",
                        "label": "Created on",
                        "value": datetime.now().strftime("%B %d, %Y")
                    }
                ]
            },
            "barcode": {
                "format": request.barcode_format.value,
                "message": request.barcode_value,
                "messageEncoding": "iso-8859-1"
            },
            "barcodes": [
                {
                    "format": request.barcode_format.value,
                    "message": request.barcode_value,
                    "messageEncoding": "iso-8859-1"
                }
            ]
        }
        return pass_json

    def _create_default_logo(self) -> bytes:
        """Create a simple default logo PNG."""
        # 1x1 transparent PNG
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        return png_data

    def _compute_manifest(self, files: dict) -> dict:
        """Compute SHA1 hashes for all files."""
        manifest = {}
        for filename, data in files.items():
            sha1 = hashlib.sha1(data).hexdigest()
            manifest[filename] = sha1
        return manifest

    def _sign_manifest(self, manifest_data: bytes) -> Optional[bytes]:
        """Sign the manifest with the certificate."""
        # Check if we have certificate configured
        if not self.cert_base64 or not self.team_id:
            print("Wallet pass signing not configured: missing WALLET_CERT_BASE64 or WALLET_TEAM_ID")
            return None

        try:
            # Decode base64 certificate
            cert_data = base64.b64decode(self.cert_base64)

            # Load WWDR certificate if provided
            wwdr_cert = None
            if self.wwdr_cert_base64:
                wwdr_data = base64.b64decode(self.wwdr_cert_base64)
                wwdr_cert = x509.load_pem_x509_certificate(wwdr_data, default_backend())

            # Parse PKCS12 certificate
            password = self.cert_password.encode() if self.cert_password else None
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                cert_data, password, default_backend()
            )

            if not private_key or not certificate:
                print("Failed to load private key or certificate from PKCS12")
                return None

            # Build certificate chain
            certs = []
            if additional_certs:
                certs.extend(additional_certs)
            if wwdr_cert:
                certs.append(wwdr_cert)

            # Create PKCS7 signature using PKCS7SignatureBuilder
            builder = pkcs7.PKCS7SignatureBuilder().set_data(manifest_data)
            builder = builder.add_signer(certificate, private_key, hashes.SHA256())

            # Add additional certificates to the signature
            for cert in certs:
                builder = builder.add_certificate(cert)

            # Sign with detached signature option
            options = [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary]
            signature = builder.sign(Encoding.DER, options)

            return signature

        except Exception as e:
            print(f"Error signing manifest: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def create_pass(self, request: WalletPassCreateRequest) -> tuple[bool, Optional[bytes], Optional[str]]:
        """
        Create a signed .pkpass file.

        Returns:
            Tuple of (success, pass_data_bytes, error_message)
        """
        try:
            serial_number = str(uuid.uuid4())

            # Create pass.json
            pass_json = self._create_pass_json(request, serial_number)
            pass_json_data = json.dumps(pass_json, indent=2).encode('utf-8')

            # Prepare files
            files = {
                "pass.json": pass_json_data
            }

            # Add logo if provided
            if request.logo_base64:
                try:
                    logo_data = base64.b64decode(request.logo_base64)
                    files["logo.png"] = logo_data
                    files["logo@2x.png"] = logo_data
                    files["icon.png"] = logo_data
                    files["icon@2x.png"] = logo_data
                except Exception:
                    # Use default logo
                    default_logo = self._create_default_logo()
                    files["logo.png"] = default_logo
                    files["logo@2x.png"] = default_logo
                    files["icon.png"] = default_logo
                    files["icon@2x.png"] = default_logo
            else:
                default_logo = self._create_default_logo()
                files["logo.png"] = default_logo
                files["logo@2x.png"] = default_logo
                files["icon.png"] = default_logo
                files["icon@2x.png"] = default_logo

            # Create manifest
            manifest = self._compute_manifest(files)
            manifest_data = json.dumps(manifest, indent=2).encode('utf-8')
            files["manifest.json"] = manifest_data

            # Sign manifest
            signature = self._sign_manifest(manifest_data)
            if signature:
                files["signature"] = signature
            else:
                # Return unsigned pass with warning
                # Note: Unsigned passes won't work with Apple Wallet
                return False, None, "Pass signing not configured. Please set WALLET_CERT_BASE64, WALLET_CERT_PASSWORD, WALLET_TEAM_ID, and WALLET_WWDR_CERT_BASE64 environment variables."

            # Create .pkpass ZIP file
            pass_buffer = BytesIO()
            with zipfile.ZipFile(pass_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filename, data in files.items():
                    zf.writestr(filename, data)

            pass_data = pass_buffer.getvalue()
            return True, pass_data, None

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, None, str(e)


# Singleton instance
wallet_pass_service = WalletPassService()
