"""Backend-served admin analytics dashboard.

Protected by HTTP Basic auth against ADMIN_DASHBOARD_PASSWORD. Renders a
single self-contained page (inline CSS + a server-drawn SVG chart) showing
subscriptions, revenue, and per-customer token usage.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from apps.billing import service as billing_service
from apps.usage import service as usage_service

router = APIRouter(prefix="/admin", tags=["Admin"])
_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """Gate the dashboard behind the configured admin password."""
    password = settings.ADMIN_DASHBOARD_PASSWORD
    if not password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin dashboard is not configured.",
        )
    ok = secrets.compare_digest(credentials.password, password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── rendering helpers ──────────────────────────────────────────────────────

_C_BG = "#0C0905"
_C_CARD = "#171009"
_C_TEXT = "#E2CCB8"
_C_MUTED = "#B89B6E"
_C_ACCENT = "#D4835A"
_C_OLIVE = "#8BAD4A"


def _bar_chart(series: list[dict]) -> str:
    """A minimal inline-SVG bar chart of daily tokens (no external deps)."""
    if not series:
        return f'<p style="color:{_C_MUTED}">No usage yet.</p>'
    w, h, pad = 720, 200, 24
    n = len(series)
    max_tok = max((d["tokens"] for d in series), default=1) or 1
    bw = (w - pad * 2) / n
    bars = []
    for i, d in enumerate(series):
        bh = (d["tokens"] / max_tok) * (h - pad * 2)
        x = pad + i * bw
        y = h - pad - bh
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bw - 3, 1):.1f}" '
            f'height="{bh:.1f}" rx="2" fill="{_C_ACCENT}"><title>'
            f'{d["date"]}: {d["tokens"]} tokens</title></rect>'
        )
    axis = (
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" '
        f'stroke="{_C_MUTED}" stroke-width="1" opacity="0.4"/>'
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" '
        f'style="max-width:{w}px">{axis}{"".join(bars)}</svg>'
    )


def _stat(label: str, value: str) -> str:
    return (
        f'<div style="background:{_C_CARD};border-radius:16px;padding:18px 20px;'
        f'min-width:150px;flex:1">'
        f'<div style="font-size:26px;font-weight:700;color:{_C_ACCENT}">{value}</div>'
        f'<div style="font-size:13px;color:{_C_MUTED};margin-top:4px">{label}</div>'
        f"</div>"
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f'<th style="text-align:left;padding:10px 12px;color:{_C_MUTED};'
        f'font-weight:600;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:.5px">{h}</th>'
        for h in headers
    )
    body = ""
    for r in rows:
        cells = "".join(
            f'<td style="padding:10px 12px;color:{_C_TEXT};font-size:14px;'
            f'border-top:1px solid rgba(200,140,80,.12)">{c}</td>'
            for c in r
        )
        body += f"<tr>{cells}</tr>"
    if not rows:
        body = (
            f'<tr><td style="padding:14px 12px;color:{_C_MUTED}" colspan="'
            f'{len(headers)}">Nothing yet.</td></tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


@router.post("/jobs/expiry-reminders")
def run_expiry_reminders(
    _admin: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Trigger the daily expiry-reminder emails. Point an external cron (Render
    Cron / cron-job.org) at this once a day; it's idempotent per cycle."""
    sent = billing_service.send_expiry_reminders(db)
    return {"reminders_sent": sent}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(
    _admin: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    stats = billing_service.admin_stats(db)
    usage_totals = usage_service.totals(db)
    series = usage_service.daily_series(db, days=30)
    top = usage_service.top_users(db, limit=15)
    payments = billing_service.recent_payments(db, limit=20)

    stat_cards = "".join(
        [
            _stat("Total users", f'{stats["total_users"]:,}'),
            _stat("Active subscribers", f'{stats["active_subscribers"]:,}'),
            _stat("On trial", f'{stats["on_trial"]:,}'),
            _stat("Gross revenue", f'₹{stats["gross_revenue_inr"]:,}'),
            _stat("Total tokens", f'{usage_totals["total_tokens"]:,}'),
            _stat("Agent turns", f'{usage_totals["turns"]:,}'),
        ]
    )

    top_rows = [
        [u["email"], u["name"] or "—", f'{u["total_tokens"]:,}', str(u["turns"])]
        for u in top
    ]
    pay_rows = [
        [
            p["created_at"], p["email"], p["provider"], p["event"],
            p["plan"], f'₹{p["amount_inr"]:,}' if p["amount_inr"] else "—",
            p["status"],
        ]
        for p in payments
    ]

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phagan · Admin</title></head>
<body style="margin:0;background:{_C_BG};color:{_C_TEXT};
  font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:28px 20px">
  <div style="max-width:960px;margin:0 auto">
    <h1 style="color:{_C_ACCENT};font-size:24px;margin:0 0 4px">Phagan · Admin</h1>
    <p style="color:{_C_MUTED};margin:0 0 24px;font-size:14px">
      Subscriptions, revenue &amp; AI token usage.</p>

    <div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:28px">
      {stat_cards}
    </div>

    <div style="background:{_C_CARD};border-radius:16px;padding:20px;margin-bottom:24px">
      <h2 style="font-size:15px;color:{_C_TEXT};margin:0 0 14px">
        Token usage · last 30 days</h2>
      {_bar_chart(series)}
    </div>

    <div style="background:{_C_CARD};border-radius:16px;padding:20px;margin-bottom:24px">
      <h2 style="font-size:15px;color:{_C_TEXT};margin:0 0 6px">
        Top token consumers</h2>
      {_table(["Email", "Name", "Tokens", "Turns"], top_rows)}
    </div>

    <div style="background:{_C_CARD};border-radius:16px;padding:20px">
      <h2 style="font-size:15px;color:{_C_TEXT};margin:0 0 6px">
        Recent payments</h2>
      {_table(
        ["When", "Email", "Provider", "Event", "Plan", "Amount", "Status"],
        pay_rows,
      )}
    </div>

    <p style="color:{_C_MUTED};font-size:12px;text-align:center;margin-top:28px">
      Active: {stats['monthly_active']} monthly · {stats['yearly_active']} yearly
    </p>
  </div>
</body></html>"""
    return HTMLResponse(html)
