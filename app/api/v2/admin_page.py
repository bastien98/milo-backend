"""
Serves the admin HTML page at /admin.

Single-page vanilla-JS admin for brand cashback campaign management.
Auth is handled client-side via Firebase Web SDK; server-side auth enforcement
lives on the /brand-cashback/admin/* API endpoints (ADMIN_UIDS allowlist).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page() -> HTMLResponse:
    settings = get_settings()
    html_path = STATIC_DIR / "admin.html"

    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Admin page not found")

    html = html_path.read_text(encoding="utf-8")

    # Inject Firebase web config from env vars. These are public values
    # (safe to expose in HTML) — access control lives on API endpoints.
    html = html.replace("__FIREBASE_API_KEY__", settings.FIREBASE_WEB_API_KEY or "")
    html = html.replace(
        "__FIREBASE_AUTH_DOMAIN__", settings.FIREBASE_WEB_AUTH_DOMAIN or ""
    )
    html = html.replace(
        "__FIREBASE_PROJECT_ID__", settings.FIREBASE_WEB_PROJECT_ID or ""
    )

    return HTMLResponse(content=html)
