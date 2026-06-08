"""Email helpers for billing notifications (Phase 2.8).

Uses Resend (https://resend.com) for transactional email. Set
RESEND_API_KEY env var to enable; otherwise falls back to logging.
"""
import logging

import resend
from nexus.config import settings

logger = logging.getLogger(__name__)


async def _send_email(to_email: str, subject: str, body_html: str) -> bool:
    if not settings.RESEND_API_KEY:
        logger.info("EMAIL (no API key, would send): to=%s subject=%s", to_email, subject)
        return False
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": settings.RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": body_html,
        })
        return True
    except Exception as e:
        logger.error("resend_send_failed to=%s err=%s", to_email, e)
        return False


async def send_usage_warning_email(tenant_id: str, metric: str, percent: float):
    subject = f"NEXUS: 您已使用 {percent:.0f}% 的 {metric} 配额"
    body = f"<p>您的 {metric} 已使用 {percent:.0f}%。<br>考虑升级计划以避免服务中断。</p>"
    await _send_email(_get_admin_email(tenant_id), subject, body)


async def send_quota_exceeded_email(tenant_id: str, metric: str, percent: float):
    subject = f"NEXUS: {metric} 配额已用尽"
    body = f"<p>您的 {metric} 已达到 {percent:.0f}%, 新请求将被拒绝。<br>请立即升级。</p>"
    await _send_email(_get_admin_email(tenant_id), subject, body)


def _get_admin_email(tenant_id: str) -> str:
    # In Phase 2.8, look up the tenant admin's email from DB.
    # For now, return a placeholder; production requires the lookup.
    return f"admin@{tenant_id}.example.com"
