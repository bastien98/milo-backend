"""PDF metadata analysis for tampering indicators."""

import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from app.services.fraud.base import BaseFraudCheck
from app.services.fraud.models import FraudSignal

logger = logging.getLogger(__name__)

# Editing software that suggests PDF was modified after creation
SUSPICIOUS_PRODUCERS = {
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
    "inkscape",
    "gimp",
    "libreoffice",
    "openoffice",
    "microsoft word",
    "google docs",
    "canva",
    "ilovepdf",
    "smallpdf",
    "sejda",
}

# Legitimate POS/scanner/mobile producers
LEGITIMATE_PRODUCERS = {
    "epson",
    "star micronics",
    "bixolon",
    "citizen",
    "zebra",
    "pos",
    "thermal",
    "receipt",
    "fiscal",
    "kassa",
    "scansnap",
    "fujitsu",
    "canon",
    "hp scan",
    "adobe scan",
    "camscanner",
    "genius scan",
    "microsoft lens",
    "ios",
    "apple",
    "iphone",
    "ipad",
}


class PdfMetadataCheck(BaseFraudCheck):
    """Checks PDF metadata for signs of tampering.

    Runs at upload time. Inspects:
    - Producer/Creator fields for editing software
    - CreationDate vs ModDate gap
    - Incremental updates (multiple xref sections)
    - Linearization (unusual for receipts)
    """

    name = "pdf_metadata"

    async def check_upload(
        self, file_content: bytes, **ctx: Any
    ) -> list[FraudSignal]:
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

        # 1. Check for editing software
        for suspicious in SUSPICIOUS_PRODUCERS:
            if suspicious in producer or suspicious in creator:
                signals.append(
                    FraudSignal(
                        check_name=self.name,
                        flag=f"editing_software_detected:{suspicious}",
                        score=1.0,
                        blocking=True,
                    )
                )
                break

        # 2. Check ModDate vs CreationDate gap
        creation_date_raw = docinfo.get("/CreationDate")
        mod_date_raw = docinfo.get("/ModDate")

        if creation_date_raw and mod_date_raw:
            cd = _parse_pdf_date(str(creation_date_raw))
            md = _parse_pdf_date(str(mod_date_raw))
            if cd and md:
                delta = abs((md - cd).total_seconds())
                if delta > 86400:  # >24 hours
                    signals.append(
                        FraudSignal(
                            check_name=self.name,
                            flag=f"mod_date_suspicious:delta_{int(delta)}s",
                            score=1.0,
                            blocking=True,
                        )
                    )
                elif delta > 3600:  # >1 hour
                    signals.append(
                        FraudSignal(
                            check_name=self.name,
                            flag=f"mod_date_gap:{int(delta)}s",
                            score=1.0,
                            blocking=True,
                        )
                    )

        # 3. Check for incremental updates (multiple xref sections)
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

        # 4. Check for linearization (unusual for receipts)
        if b"/Linearized" in file_content[:1024]:
            signals.append(
                FraudSignal(
                    check_name=self.name,
                    flag="linearized",
                    score=1.0,
                    blocking=True,
                )
            )

        pdf.close()
        return signals


def _parse_pdf_date(date_str: str) -> Optional[datetime]:
    """Parse PDF date format D:YYYYMMDDHHmmSS into datetime."""
    try:
        clean = date_str.replace("D:", "").split("+")[0].split("-")[0].split("Z")[0]
        for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
            try:
                return datetime.strptime(clean[: len(fmt.replace("%", ""))], fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None
