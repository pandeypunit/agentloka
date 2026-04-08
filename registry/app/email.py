"""Email sending via Amazon SES. Falls back to log-only when unconfigured."""

import logging
import os
from functools import lru_cache

log = logging.getLogger("agentauth.email")

SES_SENDER = os.environ.get("AGENTAUTH_EMAIL_SENDER", "AgentAuth <noreply@agentloka.ai>")
SES_REGION = os.environ.get("AGENTAUTH_SES_REGION", "ap-south-1")


@lru_cache(maxsize=1)
def _get_ses_client():
    """Lazy-init boto3 SES client. Returns None if boto3/credentials unavailable."""
    try:
        import boto3

        client = boto3.client("ses", region_name=SES_REGION)
        # Lightweight check that credentials are usable
        client.get_send_quota()
        return client
    except Exception as exc:
        log.warning("SES unavailable (%s) — emails will be logged only.", exc)
        return None


def send_verification_email(
    to: str, verify_url: str, entity_type: str = "agent", entity_name: str = ""
) -> bool:
    """Send a verification email via SES. Returns True if sent, False if logged only.

    entity_type: "agent" or "platform"
    entity_name: the agent/platform name, for the subject line
    """
    subject = f"Verify your {entity_type} '{entity_name}' on AgentAuth"

    text_body = (
        f"Click the link below to verify your {entity_type} '{entity_name}' on AgentAuth:\n\n"
        f"{verify_url}\n\n"
        f"This link expires after use. If you did not register this {entity_type}, ignore this email."
    )

    html_body = (
        f"<h2>Verify your {entity_type} on AgentAuth</h2>"
        f"<p>Click the link below to verify <strong>{entity_name}</strong>:</p>"
        f'<p><a href="{verify_url}">{verify_url}</a></p>'
        f"<p><small>This link expires after use. If you did not register this "
        f"{entity_type}, ignore this email.</small></p>"
    )

    ses = _get_ses_client()
    if ses is None:
        log.info(
            "[DEV] Verification email for %s '%s' -> %s: %s",
            entity_type, entity_name, to, verify_url,
        )
        return False

    try:
        ses.send_email(
            Source=SES_SENDER,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        log.info("Verification email sent to %s for %s '%s'", to, entity_type, entity_name)
        return True
    except Exception as exc:
        log.error("Failed to send verification email to %s: %s", to, exc)
        return False
