"""Transactional email via Resend.

All sending is best-effort and non-blocking-safe: a mail failure logs a
warning and returns False, it never raises into the caller (a webhook or a
cron job must not fail because an email bounced). Templates are small inline
HTML matching Phagan's warm palette — no external assets, so they render in
every client.
"""

from __future__ import annotations

import logging

from core.config import settings

logger = logging.getLogger(__name__)

# Brand palette (mirrors the app's light theme).
_BG = "#fffaf1"
_CARD = "#fff3dd"
_TERRACOTTA = "#A85035"
_BROWN = "#5C3D2E"
_AMBER = "#8E5D00"
_INK = "#0A0A0A"


def _shell(title: str, body_html: str, cta_label: str | None = None,
           cta_url: str | None = None) -> str:
    """Wrap body content in the branded email shell."""
    cta = ""
    if cta_label and cta_url:
        cta = f"""
        <tr><td style="padding:8px 0 4px">
          <a href="{cta_url}" style="display:inline-block;background:{_INK};
             color:{_BG};text-decoration:none;font-weight:600;font-size:15px;
             padding:13px 28px;border-radius:100px">{cta_label}</a>
        </td></tr>"""
    return f"""\
<!doctype html><html><body style="margin:0;background:{_BG};
  font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:{_BROWN}">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:32px 16px">
   <tr><td align="center">
    <table width="480" cellpadding="0" cellspacing="0"
      style="background:{_CARD};border-radius:20px;padding:36px 32px;text-align:left">
      <tr><td style="font-size:22px;font-weight:700;color:{_TERRACOTTA};
        padding-bottom:6px">Phagan</td></tr>
      <tr><td style="font-size:20px;font-weight:700;color:{_TERRACOTTA};
        padding:10px 0 14px">{title}</td></tr>
      <tr><td style="font-size:15px;line-height:1.6;color:{_BROWN}">{body_html}</td></tr>
      {cta}
      <tr><td style="padding-top:26px;font-size:12px;color:{_AMBER}">
        You're receiving this because you have a Phagan account.<br>
        © Phagan · <a href="{settings.WEBSITE_URL}"
          style="color:{_AMBER}">{settings.WEBSITE_URL.replace('https://','')}</a>
      </td></tr>
    </table>
   </td></tr>
  </table>
</body></html>"""


def send_email(to: str, subject: str, html: str) -> bool:
    """Send one email through Resend. Returns True on success."""
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email '%s' to %s", subject, to)
        return False
    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
        logger.info("Sent email '%s' to %s", subject, to)
        return True
    except Exception as e:  # noqa: BLE001 — email must never break the caller
        logger.error("Failed to send email '%s' to %s: %s", subject, to, e)
        return False


# ── Specific transactional emails ─────────────────────────────────────────

def send_welcome(to: str, name: str) -> bool:
    body = (
        f"Hi {name or 'there'},<br><br>"
        "Welcome to Phagan — your personal AI day planner. Tell it what your "
        "day looks like and it builds your todos, reminders and schedule for you."
        "<br><br>Your 3-day free trial is active. Enjoy!"
    )
    return send_email(
        to, "Welcome to Phagan 🌱",
        _shell("Welcome aboard", body, "Open Phagan", settings.WEBSITE_URL),
    )


def send_payment_success(to: str, name: str, plan: str, amount_inr: int,
                         expires_at) -> bool:
    when = expires_at.strftime("%d %b %Y") if expires_at else ""
    plan_label = "Yearly" if plan == "yearly" else "Monthly"
    body = (
        f"Hi {name or 'there'},<br><br>"
        f"Your payment for <b>Phagan Pro — {plan_label}</b> "
        f"(₹{amount_inr}) was successful. 🎉<br><br>"
        f"Your subscription is active until <b>{when}</b>. "
        "Thanks for supporting Phagan!"
    )
    return send_email(
        to, "Payment received — Phagan Pro is active",
        _shell("Payment successful", body, "Open Phagan", settings.WEBSITE_URL),
    )


def send_expiry_reminder(to: str, name: str, days_left: int, expires_at,
                        renew_url: str) -> bool:
    when = expires_at.strftime("%d %b %Y") if expires_at else ""
    day_word = "day" if days_left == 1 else "days"
    body = (
        f"Hi {name or 'there'},<br><br>"
        f"Your Phagan Pro subscription ends in <b>{days_left} {day_word}</b> "
        f"(on {when}). Renew now so your day-planning never skips a beat."
    )
    return send_email(
        to, f"Your Phagan Pro renews in {days_left} {day_word}",
        _shell("Time to renew", body, "Renew subscription", renew_url),
    )


def send_subscription_cancelled(to: str, name: str, expires_at) -> bool:
    when = expires_at.strftime("%d %b %Y") if expires_at else ""
    tail = f" You'll keep Pro access until <b>{when}</b>." if when else ""
    body = (
        f"Hi {name or 'there'},<br><br>"
        f"Your Phagan Pro subscription has been cancelled.{tail}<br><br>"
        "You can resubscribe any time — we'd love to have you back."
    )
    return send_email(
        to, "Your Phagan Pro subscription was cancelled",
        _shell("Subscription cancelled", body, "Resubscribe", settings.WEBSITE_URL),
    )
