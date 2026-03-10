"""PDF metadata analysis for tampering indicators."""

import logging
from io import BytesIO
from typing import Any

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudSignal

logger = logging.getLogger(__name__)

# Producers/creators known to indicate user-side editing or re-saving.
# Matching is case-insensitive substring. These are BLOCKING.
BLOCKED_PRODUCERS = {
    # PDF editors
    "adobe acrobat pro",
    "acrobat pro",
    "adobe acrobat",
    "pdfedit",
    "pdf-xchange",
    "nitro pro",
    "nitro pdf",
    "foxit phantompdf",
    "foxit pdf editor",
    "master pdf editor",
    "pdfgear",
    "pdf gear",
    # Image editors
    "inkscape",
    "gimp",
    # Office suites
    "libreoffice",
    "openoffice",
    "microsoft word",
    "google docs",
    # Online PDF tools
    "canva",
    "ilovepdf",
    "smallpdf",
    "sejda",
    # macOS re-save (Preview saves with "Quartz PDFContext" as producer)
    "quartz pdfcontext",
    "preview",
    # Browser save-as / print-to-PDF
    "skia",
    "pdf.js",
    "chrome",
    "firefox",
    "mozilla",
    "microsoft print to pdf",
    "edge",
    # Mobile print services
    "samsung print service",
}

# Producers/creators known to be legitimate receipt sources.
# Matching is case-insensitive substring. Checked BEFORE blocklist
# to handle ambiguity (e.g. "chromium" vs "chrome").
WHITELISTED_PRODUCERS = {
    # POS / thermal printers
    "epson",
    "star micronics",
    "bixolon",
    "citizen",
    "zebra",
    # Scanner apps
    "adobe scan",
    "camscanner",
    "genius scan",
    "microsoft lens",
    # iOS/Apple devices (share extension)
    "ios",
    "apple",
    "iphone",
    "ipad",
    # Android devices (share extension)
    "android",
    # POS / receipt keywords
    "pos",
    "thermal",
    "receipt",
    "fiscal",
    "kassa",
    # Scanner hardware
    "scansnap",
    "fujitsu",
    "canon",
    "hp scan",
    # Server-side PDF libraries (used by retailer backends)
    "itext",
    "reportlab",
    "wkhtmltopdf",
    "tcpdf",
    "fpdf",
    "mpdf",
    "jasper",
    "crystal reports",
    "apache fop",
    "pdfkit",
    "prince",
    "weasyprint",
    "puppeteer",
    "chromium",
    "headless chrome",
    # Enterprise backends
    "sap",
    "oracle",
    "cairo",
}


class PdfMetadataCheck(BaseFraudCheck):
    """Checks PDF metadata for signs of tampering.

    Runs at upload time. Inspects:
    - Producer/Creator fields for editing software
    - Incremental updates (multiple xref sections)
    """

    name = "pdf_metadata"

    def _classify_producer(
        self, producer: str, creator: str
    ) -> tuple[str, float, bool]:
        """Classify the PDF producer/creator as whitelisted, blocked, or unknown.

        Blocklist is checked first and is authoritative — a blocked match
        always results in a block. The only exception is the explicit
        "chrome" / "chromium" substring collision.

        Returns (flag, score, blocking):
          - Whitelisted or empty: ("", 0.0, False)
          - Blocked:              ("blocked_producer:<match>", 1.0, True)
          - Unknown:              ("unknown_producer:<value>", 0.4, False)
        """
        combined = f"{producer} {creator}".strip()

        if not combined:
            return ("", 0.0, False)

        # 1. Strict blocklist check
        for entry in BLOCKED_PRODUCERS:
            for field in (producer, creator):
                if entry in field:
                    # Explicit collision: "chrome" is a substring of "chromium" / "headless chrome"
                    if entry == "chrome" and ("chromium" in field or "headless chrome" in field):
                        continue
                    return (f"blocked_producer:{entry}", 1.0, True)

        # 2. Whitelist check (only runs if no blocked words found)
        for entry in WHITELISTED_PRODUCERS:
            if entry in producer or entry in creator:
                return ("", 0.0, False)

        unknown_value = producer if producer else creator
        return (f"unknown_producer:{unknown_value}", 0.4, False)

    async def check_upload(
        self, file_content: bytes, **ctx: Any
    ) -> list[FraudSignal]:
        # Skip non-PDF files (e.g. JPEG uploads)
        if not file_content.startswith(b"%PDF"):
            return []

        signals: list[FraudSignal] = []

        try:
            import pikepdf

            pdf = pikepdf.Pdf.open(BytesIO(file_content))
        except Exception as e:
            logger.warning(f"Could not parse PDF for fraud check: {e}")
            signals.append(
                FraudSignal(
                    check_name=self.name,
                    flag="pdf_parse_error",
                    score=1.0,
                    blocking=True,
                )
            )
            return signals

        docinfo = pdf.docinfo
        producer = str(docinfo.get("/Producer", "")).lower()
        creator = str(docinfo.get("/Creator", "")).lower()

        # 1. Producer/creator whitelist check
        flag, score, blocking = self._classify_producer(producer, creator)
        if flag:
            signals.append(
                FraudSignal(
                    check_name=self.name,
                    flag=flag,
                    score=score,
                    blocking=blocking,
                )
            )
            if flag.startswith("unknown_producer"):
                logger.warning(
                    f"Unknown PDF producer: producer='{producer}', creator='{creator}'"
                )

        # 2. Check for incremental updates (multiple xref sections)
        xref_count = file_content.count(b"startxref")
        if xref_count > 1:
            signals.append(
                FraudSignal(
                    check_name=self.name,
                    flag=f"incremental_updates:{xref_count}",
                    score=1.0,
                    blocking=True,
                )
            )

        pdf.close()
        return signals
