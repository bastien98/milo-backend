from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.models.enums import PromoReportStatus

BRUSSELS_TZ = ZoneInfo("Europe/Brussels")


def current_brussels_date() -> date:
    return datetime.now(BRUSSELS_TZ).date()


def compute_promo_week(report_date: Optional[date] = None) -> dict:
    """Return the promo week (Mon-Sun) in Europe/Brussels ISO calendar."""
    today = report_date or current_brussels_date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    iso = today.isocalendar()
    return {
        "start": monday.strftime("%d/%m"),
        "end": sunday.strftime("%d/%m"),
        "label": f"Week {iso[1]}",
        "iso_year": iso[0],
        "iso_week": iso[1],
    }


def build_empty_promo_response(
    report_status: PromoReportStatus = PromoReportStatus.READY,
    message: str = "No active deals matched your habits this week.",
    report_date: Optional[date] = None,
) -> dict:
    week = compute_promo_week(report_date)
    return {
        "report_id": None,
        "report_status": report_status.value,
        "message": message,
        "generated_at": None,
        "weekly_savings": 0,
        "deal_count": 0,
        "promo_week": week,
        "top_picks": [],
        "stores": [],
        "smart_switch": None,
        "summary": {
            "total_items": 0,
            "total_savings": 0,
            "stores_breakdown": [],
            "best_value_store": None,
            "best_value_savings": 0,
            "best_value_items": 0,
            "closing_nudge": message,
        },
    }
