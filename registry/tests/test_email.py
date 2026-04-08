"""Unit tests for the SES email sender module."""

from unittest.mock import MagicMock, patch


def test_send_email_success():
    """When SES client is available, send_email is called and returns True."""
    mock_ses = MagicMock()
    with patch("registry.app.email._get_ses_client", return_value=mock_ses):
        from registry.app.email import send_verification_email

        result = send_verification_email(
            "user@test.com", "https://example.com/verify/abc", "agent", "test_bot"
        )
        assert result is True
        mock_ses.send_email.assert_called_once()
        call_kwargs = mock_ses.send_email.call_args[1]
        assert call_kwargs["Destination"] == {"ToAddresses": ["user@test.com"]}
        assert "test_bot" in call_kwargs["Message"]["Subject"]["Data"]


def test_send_email_graceful_degradation():
    """When SES client is None (no credentials), returns False and logs."""
    with patch("registry.app.email._get_ses_client", return_value=None):
        from registry.app.email import send_verification_email

        result = send_verification_email(
            "user@test.com", "https://example.com/verify/abc", "agent", "test_bot"
        )
        assert result is False


def test_send_email_ses_error():
    """When SES raises an exception, returns False and doesn't crash."""
    mock_ses = MagicMock()
    mock_ses.send_email.side_effect = Exception("SES throttled")
    with patch("registry.app.email._get_ses_client", return_value=mock_ses):
        from registry.app.email import send_verification_email

        result = send_verification_email(
            "user@test.com", "https://example.com/verify/abc", "agent", "test_bot"
        )
        assert result is False


def test_send_email_platform_type():
    """Platform emails use entity_type='platform' in the subject."""
    mock_ses = MagicMock()
    with patch("registry.app.email._get_ses_client", return_value=mock_ses):
        from registry.app.email import send_verification_email

        result = send_verification_email(
            "admin@test.com", "https://example.com/verify/xyz", "platform", "my_plat"
        )
        assert result is True
        call_kwargs = mock_ses.send_email.call_args[1]
        assert "platform" in call_kwargs["Message"]["Subject"]["Data"]
        assert "my_plat" in call_kwargs["Message"]["Subject"]["Data"]
