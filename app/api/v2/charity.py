import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.charity import (
    CharityListResponse,
    CharityItem,
    CharityDonateRequest,
    CharityDonateResponse,
    CharityHistoryResponse,
    CharityDonationItem,
    CharityAdminDonationItem,
    CharityAdminSummaryItem,
)
from app.services.charity_service import CharityService, BELGIAN_CHARITIES

router = APIRouter()

ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]


async def require_admin(current_user: User = Depends(get_current_db_user)):
    if not current_user.email or current_user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ────────────────── User endpoints ──────────────────


@router.get("/list", response_model=CharityListResponse)
async def list_charities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """List all 6 Belgian charities with community totals and the user's contribution."""
    svc = CharityService(db)
    charities, user_balance = await svc.get_charities_with_totals(current_user.id)
    return CharityListResponse(
        charities=[CharityItem(**c) for c in charities],
        user_balance=user_balance,
    )


@router.post("/donate", response_model=CharityDonateResponse)
async def donate(
    body: CharityDonateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Create a charity donation from the user's wallet balance."""
    svc = CharityService(db)
    try:
        result = await svc.create_donation(current_user, body.charity_id, body.amount)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history", response_model=CharityHistoryResponse)
async def get_donation_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get the current user's charity donation history."""
    svc = CharityService(db)
    donations, total = await svc.get_user_donations(current_user.id)
    return CharityHistoryResponse(
        donations=[CharityDonationItem.model_validate(d) for d in donations],
        total_donated=round(total, 2),
    )


# ────────────────── Admin endpoints ──────────────────


@router.get("/admin/pending", response_model=list[CharityAdminDonationItem])
async def admin_list_pending(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list all pending charity donations."""
    svc = CharityService(db)
    donations = await svc.get_all_pending()
    return [
        CharityAdminDonationItem(
            **{k: v for k, v in d.__dict__.items() if not k.startswith("_")},
            user_email=d.user.email if d.user else None,
        )
        for d in donations
    ]


@router.get("/admin/all", response_model=list[CharityAdminDonationItem])
async def admin_list_all(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: list all charity donations."""
    svc = CharityService(db)
    donations = await svc.get_all_donations()
    return [
        CharityAdminDonationItem(
            **{k: v for k, v in d.__dict__.items() if not k.startswith("_")},
            user_email=d.user.email if d.user else None,
        )
        for d in donations
    ]


@router.post("/admin/{donation_id}/transferred")
async def admin_mark_transferred(
    donation_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: mark a single donation as transferred."""
    svc = CharityService(db)
    try:
        donation = await svc.mark_transferred(donation_id)
        await db.commit()
        return CharityDonationItem.model_validate(donation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/charity/{charity_id}/transfer-all")
async def admin_transfer_all_for_charity(
    charity_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: mark all pending donations for a charity as transferred."""
    svc = CharityService(db)
    count = await svc.mark_charity_transferred(charity_id)
    await db.commit()
    return {"transferred": count, "charity_id": charity_id}


# ────────────────── HTML Admin Panel ──────────────────

_STATUS_COLOR = {"pending": "#f59e0b", "transferred": "#10b981"}
_CHARITY_ICONS = {
    "rode_kruis":    "❤️",
    "msf_belgium":   "🩺",
    "unicef_belgium":"🌍",
    "plan_belgium":  "🌱",
    "oxfam_belgium": "🤝",
    "handicap_intl": "♿",
}


def _render_admin_html(summary: list[dict], recent: list, base_url: str) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Summary cards
    cards_html = ""
    for item in summary:
        icon = _CHARITY_ICONS.get(item["charity_id"], "🤝")
        pending_total = item["pending_total"]
        transferred_total = item["transferred_total"]
        pending_count = item["pending_count"]
        cards_html += f"""
        <div class="card">
          <div class="card-header">
            <span class="icon">{icon}</span>
            <span class="charity-name">{item["charity_name"]}</span>
          </div>
          <div class="stats">
            <div class="stat pending">
              <div class="stat-value">€{pending_total:.2f}</div>
              <div class="stat-label">Pending ({pending_count} donations)</div>
            </div>
            <div class="stat transferred">
              <div class="stat-value">€{transferred_total:.2f}</div>
              <div class="stat-label">Transferred</div>
            </div>
          </div>
          {"" if pending_count == 0 else f'''
          <form method="POST" action="{base_url}/charity/admin/charity/{item["charity_id"]}/transfer-all" style="margin-top:12px">
            <button type="submit" class="btn-transfer">✓ Mark all €{pending_total:.2f} as transferred</button>
          </form>'''}
        </div>
        """

    # Recent donations table rows
    rows_html = ""
    for d in recent[:50]:
        status_color = _STATUS_COLOR.get(d.status.value if hasattr(d.status, "value") else str(d.status), "#94a3b8")
        email = d.user.email if d.user else "—"
        date_str = d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "—"
        icon = _CHARITY_ICONS.get(d.charity_id, "🤝")
        rows_html += f"""
        <tr>
          <td>{date_str}</td>
          <td>{email}</td>
          <td>{icon} {d.charity_name}</td>
          <td>€{d.amount:.2f}</td>
          <td><span class="badge" style="background:{status_color}">{d.status.value if hasattr(d.status, "value") else d.status}</span></td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Milo – Charity Donations Admin</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 24px; }}
    h1 {{ font-size: 24px; font-weight: 800; margin-bottom: 4px; }}
    .subtitle {{ color: #64748b; font-size: 13px; margin-bottom: 32px; }}
    h2 {{ font-size: 16px; font-weight: 700; color: #94a3b8; text-transform: uppercase;
          letter-spacing: 0.08em; margin-bottom: 16px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
              gap: 16px; margin-bottom: 40px; }}
    .card {{ background: #1e293b; border-radius: 16px; padding: 20px;
             border: 1px solid #334155; }}
    .card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
    .icon {{ font-size: 24px; }}
    .charity-name {{ font-size: 15px; font-weight: 700; }}
    .stats {{ display: flex; gap: 16px; }}
    .stat {{ flex: 1; }}
    .stat-value {{ font-size: 22px; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .stat.pending .stat-value {{ color: #f59e0b; }}
    .stat.transferred .stat-value {{ color: #10b981; }}
    .stat-label {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
    .btn-transfer {{ background: #10b981; color: white; border: none; border-radius: 10px;
                    padding: 10px 16px; font-size: 13px; font-weight: 700; cursor: pointer;
                    width: 100%; transition: opacity 0.2s; }}
    .btn-transfer:hover {{ opacity: 0.85; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b;
             border-radius: 16px; overflow: hidden; border: 1px solid #334155; }}
    th {{ text-align: left; padding: 12px 16px; font-size: 11px; font-weight: 700;
          color: #64748b; text-transform: uppercase; letter-spacing: 0.06em;
          background: #0f172a; border-bottom: 1px solid #334155; }}
    td {{ padding: 12px 16px; font-size: 13px; border-bottom: 1px solid #1e293b; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,0.02); }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px;
              font-size: 11px; font-weight: 700; color: white; }}
    .refresh {{ color: #64748b; font-size: 12px; margin-bottom: 16px; }}
    a.refresh-link {{ color: #7c3aed; text-decoration: none; }}
  </style>
</head>
<body>
  <h1>🤝 Charity Donations</h1>
  <p class="subtitle">Milo Admin Panel · Last loaded: {now} ·
    <a href="{base_url}/charity/admin/panel" class="refresh-link">Refresh</a></p>

  <h2>Summary by Charity</h2>
  <div class="cards">{cards_html}</div>

  <h2>Recent Donations (last 50)</h2>
  <table>
    <thead>
      <tr>
        <th>Date</th><th>User</th><th>Charity</th><th>Amount</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>"""


@router.get("/admin/panel", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin: HTML dashboard for tracking charity donations."""
    svc = CharityService(db)
    summary = await svc.get_admin_summary()
    recent = await svc.get_all_donations()
    base_url = f"{request.base_url}api/v2"
    # strip trailing slash
    base_url = base_url.rstrip("/")
    html = _render_admin_html(summary, recent, base_url)
    return HTMLResponse(content=html)
