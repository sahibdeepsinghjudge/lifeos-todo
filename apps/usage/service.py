"""Recording and aggregating LLM token usage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import IST
from apps.usage.models import TokenUsage

logger = logging.getLogger(__name__)


def record_usage(
    db: Session, user_id: int, model: str, usage: dict | None
) -> None:
    """Persist one turn's token usage. Best-effort — never breaks the chat."""
    if not usage:
        return
    total = usage.get("total_tokens") or 0
    if total <= 0 and not (usage.get("prompt_tokens") or usage.get("completion_tokens")):
        return
    try:
        db.add(
            TokenUsage(
                user_id=user_id,
                model=model or "",
                prompt_tokens=usage.get("prompt_tokens") or 0,
                completion_tokens=usage.get("completion_tokens") or 0,
                total_tokens=total,
                usage_date=datetime.now(IST).date(),
            )
        )
        db.commit()
    except Exception as e:  # noqa: BLE001 — metering must not sink the request
        logger.warning("Failed to record token usage for user %s: %s", user_id, e)
        db.rollback()


def totals(db: Session) -> dict:
    """Overall token + turn counts across all users."""
    row = db.query(
        func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
        func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
        func.count(TokenUsage.id),
    ).one()
    return {
        "total_tokens": int(row[0]),
        "prompt_tokens": int(row[1]),
        "completion_tokens": int(row[2]),
        "turns": int(row[3]),
    }


def daily_series(db: Session, days: int = 30) -> list[dict]:
    """Total tokens per day for the last `days` days (oldest first)."""
    since = datetime.now(IST).date() - timedelta(days=days - 1)
    rows = (
        db.query(
            TokenUsage.usage_date,
            func.sum(TokenUsage.total_tokens),
            func.count(TokenUsage.id),
        )
        .filter(TokenUsage.usage_date >= since)
        .group_by(TokenUsage.usage_date)
        .order_by(TokenUsage.usage_date)
        .all()
    )
    return [
        {"date": r[0].isoformat(), "tokens": int(r[1] or 0), "turns": int(r[2])}
        for r in rows
    ]


def top_users(db: Session, limit: int = 20) -> list[dict]:
    """Highest token-consuming users."""
    from apps.auth.models import User

    rows = (
        db.query(
            User.id,
            User.email,
            User.name,
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            func.count(TokenUsage.id),
        )
        .join(TokenUsage, TokenUsage.user_id == User.id)
        .group_by(User.id, User.email, User.name)
        .order_by(func.sum(TokenUsage.total_tokens).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "user_id": r[0],
            "email": r[1],
            "name": r[2],
            "total_tokens": int(r[3]),
            "turns": int(r[4]),
        }
        for r in rows
    ]
