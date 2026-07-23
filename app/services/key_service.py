"""API key generation, hashing, and usage accounting."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ApiKey, UsageLog, User

KEY_PREFIX_TOKEN = "ah_live_"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_raw_api_key() -> str:
    # ah_live_ + 32 bytes hex = readable, high entropy
    return f"{KEY_PREFIX_TOKEN}{secrets.token_hex(24)}"


def key_display_prefix(raw_key: str) -> str:
    return raw_key[:12]


def get_or_create_user(db: Session, email: str) -> User:
    normalized = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized))
    if user:
        return user
    user = User(email=normalized)
    db.add(user)
    db.flush()
    return user


def issue_api_key(db: Session, email: str) -> tuple[str, ApiKey, User]:
    """Create a new API key for email. Returns (raw_key, api_key_row, user)."""
    settings = get_settings()
    user = get_or_create_user(db, email)
    raw = generate_raw_api_key()
    row = ApiKey(
        user_id=user.id,
        key_prefix=key_display_prefix(raw),
        key_hash=hash_api_key(raw),
        is_active=True,
        daily_limit=settings.free_tier_daily_limit,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    db.refresh(user)
    return raw, row, user


def find_active_key_by_raw(db: Session, raw_key: str) -> ApiKey | None:
    digest = hash_api_key(raw_key)
    return db.scalar(
        select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.is_active.is_(True))
    )


def _start_of_utc_day(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def count_usage_today(db: Session, api_key_id: int) -> int:
    start = _start_of_utc_day()
    return int(
        db.scalar(
            select(func.count())
            .select_from(UsageLog)
            .where(UsageLog.api_key_id == api_key_id, UsageLog.timestamp >= start)
        )
        or 0
    )


def count_usage_month(db: Session, api_key_id: int) -> int:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    return int(
        db.scalar(
            select(func.count())
            .select_from(UsageLog)
            .where(UsageLog.api_key_id == api_key_id, UsageLog.timestamp >= start)
        )
        or 0
    )


def record_usage(
    db: Session,
    *,
    api_key_id: int,
    endpoint: str,
    status_code: int,
) -> None:
    db.add(
        UsageLog(
            api_key_id=api_key_id,
            endpoint=endpoint[:512],
            status_code=status_code,
        )
    )
    db.commit()


def usage_snapshot(db: Session, api_key: ApiKey) -> dict[str, Any]:
    used_today = count_usage_today(db, api_key.id)
    used_month = count_usage_month(db, api_key.id)
    remaining = max(api_key.daily_limit - used_today, 0)
    return {
        "key_prefix": api_key.key_prefix,
        "plan": "free",
        "daily_limit": api_key.daily_limit,
        "used_today": used_today,
        "remaining_today": remaining,
        "used_month": used_month,
        "is_active": api_key.is_active,
    }
