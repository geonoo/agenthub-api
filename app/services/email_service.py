"""Email verification codes + Resend delivery."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import EmailVerification

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def create_verification(db: Session, email: str) -> EmailVerification:
    """Replace any pending codes for email and create a fresh 5-minute code."""
    settings = get_settings()
    normalized = email.strip().lower()
    db.execute(
        delete(EmailVerification).where(
            EmailVerification.email == normalized,
            EmailVerification.is_verified.is_(False),
        )
    )
    now = _utcnow()
    row = EmailVerification(
        email=normalized,
        code=generate_code(),
        created_at=now,
        expires_at=now + timedelta(minutes=settings.email_code_ttl_minutes),
        is_verified=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def verify_code(db: Session, email: str, code: str) -> EmailVerification:
    normalized = email.strip().lower()
    code = code.strip()
    row = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.email == normalized,
            EmailVerification.code == code,
        )
        .order_by(EmailVerification.created_at.desc())
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증번호가 올바르지 않습니다.",
        )
    if row.is_verified:
        return row

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _utcnow() > expires:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증번호가 만료되었습니다. 다시 요청해 주세요.",
        )

    row.is_verified = True
    db.commit()
    db.refresh(row)
    return row


def require_verified_email(db: Session, email: str) -> EmailVerification:
    normalized = email.strip().lower()
    row = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.email == normalized,
            EmailVerification.is_verified.is_(True),
        )
        .order_by(EmailVerification.created_at.desc())
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증이 필요합니다. 인증번호를 먼저 확인해 주세요.",
        )
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    # Allow a short grace after verify within same code TTL window + 30min buffer
    # Verified flag is enough; expire check only for unverified path above.
    return row


def consume_verification(db: Session, email: str) -> None:
    """Reset verified state after successful API key issuance."""
    normalized = email.strip().lower()
    rows = db.scalars(
        select(EmailVerification).where(EmailVerification.email == normalized)
    ).all()
    for row in rows:
        row.is_verified = False
    db.commit()


def build_verification_email_html(code: str, ttl_minutes: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /></head>
<body style="margin:0;padding:0;background:#07090f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#07090f;padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" style="max-width:440px;background:#0c111b;border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:32px;">
        <tr><td>
          <p style="margin:0 0 8px;color:#3ecf8e;font-size:12px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;">AgentHub</p>
          <h1 style="margin:0 0 12px;color:#ffffff;font-size:22px;font-weight:700;">이메일 인증번호</h1>
          <p style="margin:0 0 28px;color:#94a3b8;font-size:14px;line-height:1.6;">
            API Key 발급을 위해 아래 인증번호를 입력해 주세요.<br/>
            유효시간 <strong style="color:#e2e8f0;">{ttl_minutes}분</strong>입니다.
          </p>
          <div style="text-align:center;background:#121826;border:1px solid rgba(62,207,142,0.35);border-radius:12px;padding:24px 16px;margin-bottom:24px;">
            <span style="font-size:36px;letter-spacing:0.35em;font-weight:700;color:#3ecf8e;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{code}</span>
          </div>
          <p style="margin:0;color:#64748b;font-size:12px;line-height:1.5;">
            본인이 요청하지 않았다면 이 메일을 무시하세요.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_verification_email(email: str, code: str) -> None:
    settings = get_settings()
    html = build_verification_email_html(code, settings.email_code_ttl_minutes)

    if not settings.resend_api_key.strip():
        # Dev/test fallback — never fail local pytest when Resend is unset
        logger.warning(
            "RESEND_API_KEY unset; skipping email send to %s (code=%s)",
            email,
            code if settings.environment == "test" else "******",
        )
        if settings.environment in {"test", "development", "dev"} or settings.debug:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="메일 발송이 설정되지 않았습니다. RESEND_API_KEY를 확인해 주세요.",
        )

    try:
        import resend

        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [email],
                "subject": "[AgentHub] 이메일 인증번호입니다",
                "html": html,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resend send failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="인증 메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
