"""Agent key derivation from master key using HKDF-SHA256.

Derives deterministic Ed25519 keypairs for individual agents.
Same master key + same agent name = same derived key every time.
"""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def derive_agent_key(
    master_private_key: bytes,
    agent_name: str,
) -> tuple[bytes, bytes]:
    """Derive a deterministic Ed25519 keypair for an agent.

    Uses HKDF-SHA256 with the master private key as input key material
    and the agent name as the info/context parameter.

    Args:
        master_private_key: Raw 32-byte master private key.
        agent_name: Globally unique agent name.

    Returns:
        (agent_private_key_bytes, agent_public_key_bytes) — raw 32-byte keys.
    """
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=agent_name.encode("utf-8"),
    )
    agent_seed = hkdf.derive(master_private_key)

    agent_private_key = Ed25519PrivateKey.from_private_bytes(agent_seed)
    agent_private_bytes = agent_private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    agent_public_bytes = agent_private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return agent_private_bytes, agent_public_bytes


def sign_message(private_key: bytes, message: bytes) -> bytes:
    """Sign a message with an Ed25519 private key.

    Args:
        private_key: Raw 32-byte Ed25519 private key.
        message: The message bytes to sign.

    Returns:
        64-byte Ed25519 signature.
    """
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    return key.sign(message)


def verify_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature.

    Args:
        public_key: Raw 32-byte Ed25519 public key.
        message: The original message bytes.
        signature: The 64-byte signature to verify.

    Returns:
        True if valid, False otherwise.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    key = Ed25519PublicKey.from_public_bytes(public_key)
    try:
        key.verify(signature, message)
        return True
    except InvalidSignature:
        return False
