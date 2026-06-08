"""Verify Resend email integration is wired (with Resend SDK mocked)."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_usage_warning_email_calls_resend_when_api_key_set():
    """When RESEND_API_KEY is set, send should call resend.Emails.send."""
    with patch("nexus.services.billing_email.resend") as mock_resend, \
         patch("nexus.config.settings.RESEND_API_KEY", "re_test_key"):
        from nexus.services.billing_email import send_usage_warning_email
        await send_usage_warning_email("test_tenant", "tokens", 85.0)
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "85" in call_kwargs["subject"]


@pytest.mark.asyncio
async def test_quota_exceeded_email_calls_resend():
    with patch("nexus.services.billing_email.resend") as mock_resend, \
         patch("nexus.config.settings.RESEND_API_KEY", "re_test_key"):
        from nexus.services.billing_email import send_quota_exceeded_email
        await send_quota_exceeded_email("test_tenant", "tokens", 110.0)
        mock_resend.Emails.send.assert_called_once()
