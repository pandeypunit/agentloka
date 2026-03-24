"""Signature verification for authenticated registry endpoints."""

from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request

MAX_TIMESTAMP_DRIFT = timedelta(minutes=5)


async def verify_request_signature(request: Request) -> str:
    """Verify Ed25519 signature on request. Returns the public key hex.

    Expected headers:
        X-AgentAuth-PublicKey: hex-encoded public key
        X-AgentAuth-Signature: hex-encoded signature
        X-AgentAuth-Timestamp: ISO 8601 UTC timestamp

    Signed message format: "{timestamp}\n{request_body}"
    """
    public_key_hex = request.headers.get("X-AgentAuth-PublicKey")
    signature_hex = request.headers.get("X-AgentAuth-Signature")
    timestamp_str = request.headers.get("X-AgentAuth-Timestamp")

    if not all([public_key_hex, signature_hex, timestamp_str]):
        raise HTTPException(
            status_code=401,
            detail="Missing auth headers: X-AgentAuth-PublicKey, X-AgentAuth-Signature, X-AgentAuth-Timestamp",
        )

    # Validate timestamp to prevent replay attacks
    try:
        timestamp = datetime.fromisoformat(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp format")

    now = datetime.now(UTC)
    if abs(now - timestamp) > MAX_TIMESTAMP_DRIFT:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in the future")

    # Read and verify body
    body = await request.body()

    message = f"{timestamp_str}\n".encode() + body

    try:
        public_key_bytes = bytes.fromhex(public_key_hex)
        signature_bytes = bytes.fromhex(signature_hex)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature_bytes, message)
    except (ValueError, InvalidSignature):
        raise HTTPException(status_code=403, detail="Signature verification failed")

    return public_key_hex
