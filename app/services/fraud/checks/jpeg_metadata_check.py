"""JPEG EXIF metadata and forensic analysis for tampering indicators."""

import logging
import struct
from io import BytesIO
from typing import Any

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudSignal

logger = logging.getLogger(__name__)

# JPEG magic bytes — skip non-JPEG files early.
_JPEG_MAGIC = b"\xff\xd8\xff"

# Software tags known to indicate image editing. Case-insensitive substring matching.
BLOCKED_SOFTWARE = {
    # Image editors
    "adobe photoshop",
    "photoshop",
    "gimp",
    "pixelmator",
    "affinity photo",
    "paint.net",
    "corel",
    "photopea",
    # Mobile editors
    "snapseed",
    "picsart",
    "vsco",
    "lightroom",
    "adobe lightroom",
    # Design tools
    "canva",
    "figma",
    # macOS re-save
    "preview",
    # Online tools
    "fotor",
    "befunky",
    "pixlr",
}

# Software tags known to be legitimate receipt image sources.
WHITELISTED_SOFTWARE = {
    # Delhaize / SuperPlus app
    "delhaize",
    "superplus",
    "ahold",
    # iOS system
    "ios",
    "apple",
    "iphone",
    "ipad",
    # Android system
    "android",
    "samsung",
    "google",
    # Scanner apps
    "adobe scan",
    "camscanner",
    "genius scan",
    "microsoft lens",
    # Receipt / POS keywords
    "receipt",
    "pos",
    "thermal",
    "fiscal",
    "kassa",
}

# Standard JPEG quantization tables (from the JPEG spec, Annex K).
# Used to detect double-compression: an original JPEG saved once will have
# tables close to these standards or to camera-specific tables. A re-saved
# JPEG (opened in editor → saved again) diverges significantly.
_STANDARD_LUMINANCE_TABLE = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]


def _extract_quantization_tables(file_content: bytes) -> list[list[int]]:
    """Extract quantization tables from raw JPEG bytes by parsing DQT markers.

    Uses bytes.find() to jump to DQT (0xFF 0xDB) markers at C-level speed
    instead of iterating byte-by-byte in Python.

    Returns a list of 64-element tables (one per DQT segment found).
    """
    tables: list[list[int]] = []

    # Only scan up to SOS marker — no DQT tables appear after it.
    sos_pos = file_content.find(b"\xff\xda")
    header = file_content[:sos_pos] if sos_pos != -1 else file_content

    i = 0
    while True:
        i = header.find(b"\xff\xdb", i)
        if i == -1:
            break

        if i + 4 > len(header):
            break
        length = struct.unpack(">H", header[i + 2:i + 4])[0]
        segment = header[i + 4:i + 2 + length]

        pos = 0
        while pos < len(segment):
            precision_and_id = segment[pos]
            precision = (precision_and_id >> 4) & 0x0F  # 0 = 8-bit, 1 = 16-bit
            pos += 1
            if precision == 0:
                # 8-bit values
                if pos + 64 > len(segment):
                    break
                table = list(segment[pos:pos + 64])
                tables.append(table)
                pos += 64
            else:
                # 16-bit values
                if pos + 128 > len(segment):
                    break
                table = []
                for j in range(64):
                    val = struct.unpack(">H", segment[pos + j * 2:pos + j * 2 + 2])[0]
                    table.append(val)
                tables.append(table)
                pos += 128

        i += 2 + length

    return tables


def _quantization_table_divergence(table: list[int]) -> float:
    """Compute mean absolute percentage divergence from the standard luminance table.

    A table from a single-compression JPEG (quality ~75-95) will be a scaled
    version of the standard table. Double-compression produces tables that
    don't scale cleanly, resulting in higher divergence.

    Returns a divergence score (0 = identical to standard, higher = more divergent).
    """
    if len(table) != 64:
        return 0.0

    # Find the best-fit quality scale factor (ratio of table to standard)
    ratios = []
    for t_val, s_val in zip(table, _STANDARD_LUMINANCE_TABLE):
        if s_val > 0 and t_val > 0:
            ratios.append(t_val / s_val)

    if not ratios:
        return 0.0

    median_ratio = sorted(ratios)[len(ratios) // 2]

    # Compute divergence from the scaled standard
    total_div = 0.0
    for t_val, s_val in zip(table, _STANDARD_LUMINANCE_TABLE):
        expected = s_val * median_ratio
        if expected > 0:
            total_div += abs(t_val - expected) / expected

    return total_div / 64


class JpegMetadataCheck(BaseFraudCheck):
    """Checks JPEG EXIF metadata and image forensics for signs of tampering.

    Runs at upload time. Inspects:
    - Software/ProcessingSoftware EXIF fields for editing tools
    - Presence of EXIF data (stripped EXIF is suspicious)
    - Quantization table divergence (double-compression detection)
    """

    name = "jpeg_metadata"

    # Quantization divergence above this threshold flags double-compression.
    QT_DIVERGENCE_THRESHOLD = 0.35

    def _classify_software(
        self, software: str, processing_software: str
    ) -> tuple[str, float, bool]:
        """Classify the JPEG software field as whitelisted, blocked, or unknown.

        Returns (flag, score, blocking).
        """
        combined = f"{software} {processing_software}".strip()

        if not combined:
            return ("", 0.0, False)

        lower = combined.lower()

        # 1. Blocklist check
        for entry in BLOCKED_SOFTWARE:
            if entry in lower:
                return (f"blocked_software:{entry}", 1.0, True)

        # 2. Whitelist check
        for entry in WHITELISTED_SOFTWARE:
            if entry in lower:
                return ("", 0.0, False)

        return (f"unknown_software:{software or processing_software}", 0.4, False)

    def _check_quantization_tables(self, file_content: bytes) -> list[FraudSignal]:
        """Detect double-compression via quantization table analysis."""
        signals: list[FraudSignal] = []

        try:
            tables = _extract_quantization_tables(file_content)
            if not tables:
                return signals

            # Check the first table (luminance — most informative)
            divergence = _quantization_table_divergence(tables[0])

            if divergence > self.QT_DIVERGENCE_THRESHOLD:
                signals.append(
                    FraudSignal(
                        check_name=self.name,
                        flag=f"double_compression:divergence={divergence:.3f}",
                        score=0.3,
                        blocking=False,
                    )
                )
                logger.warning(
                    f"JPEG quantization table divergence {divergence:.3f} "
                    f"exceeds threshold {self.QT_DIVERGENCE_THRESHOLD} — possible double-compression"
                )
        except Exception as e:
            logger.debug(f"Quantization table analysis failed: {e}")

        return signals

    async def check_upload(
        self, file_content: bytes, **ctx: Any
    ) -> list[FraudSignal]:
        # Skip non-JPEG files
        if not file_content[:3] == _JPEG_MAGIC:
            return []

        signals: list[FraudSignal] = []

        try:
            from PIL import Image
            from PIL.ExifTags import Base as ExifBase

            img = Image.open(BytesIO(file_content))
            exif = img.getexif()

            if not exif:
                # No EXIF data at all — suspicious (common after editing + stripping)
                signals.append(
                    FraudSignal(
                        check_name=self.name,
                        flag="exif_stripped",
                        score=0.4,
                        blocking=False,
                    )
                )
                logger.warning("JPEG has no EXIF data — possible metadata stripping")
            else:
                # Check Software (tag 0x0131) and ProcessingSoftware (tag 0x000b)
                software = str(exif.get(ExifBase.Software, "") or "")
                processing_software = str(exif.get(0x000B, "") or "")  # ProcessingSoftware

                flag, score, blocking = self._classify_software(software, processing_software)
                if flag:
                    signals.append(
                        FraudSignal(
                            check_name=self.name,
                            flag=flag,
                            score=score,
                            blocking=blocking,
                        )
                    )
                    if flag.startswith("unknown_software"):
                        logger.warning(
                            f"Unknown JPEG software: software='{software}', "
                            f"processing_software='{processing_software}'"
                        )

            img.close()

        except Exception as e:
            logger.warning(f"Could not read JPEG EXIF data: {e}")
            signals.append(
                FraudSignal(
                    check_name=self.name,
                    flag="exif_read_error",
                    score=0.2,
                    blocking=False,
                )
            )

        # Quantization table analysis (double-compression detection)
        signals.extend(self._check_quantization_tables(file_content))

        return signals
