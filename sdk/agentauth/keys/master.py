"""Master key generation and storage.

Generates Ed25519 keypairs and stores them at ~/.config/agentauth/master_key.json.
The master key is the root of trust — all agent keys are derived from it.
"""

import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "agentauth"
MASTER_KEY_FILE = "master_key.json"


def generate_master_key() -> tuple[bytes, bytes]:
    """Generate a new Ed25519 master keypair.

    Returns:
        (private_key_bytes, public_key_bytes) — raw 32-byte keys.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return private_bytes, public_bytes


def save_master_key(
    private_key: bytes,
    public_key: bytes,
    config_dir: Path | None = None,
) -> Path:
    """Save master keypair to disk with restrictive permissions.

    Args:
        private_key: Raw 32-byte Ed25519 private key.
        public_key: Raw 32-byte Ed25519 public key.
        config_dir: Directory to store the key file. Defaults to ~/.config/agentauth/.

    Returns:
        Path to the saved key file.
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    key_path = config_dir / MASTER_KEY_FILE
    data = {
        "private_key": private_key.hex(),
        "public_key": public_key.hex(),
    }

    key_path.write_text(json.dumps(data, indent=2))
    # Owner read/write only — this is the crown jewel
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

    return key_path


def load_master_key(config_dir: Path | None = None) -> tuple[bytes, bytes]:
    """Load master keypair from disk.

    Args:
        config_dir: Directory containing the key file. Defaults to ~/.config/agentauth/.

    Returns:
        (private_key_bytes, public_key_bytes)

    Raises:
        FileNotFoundError: If no master key exists. Run `agentauth init` first.
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    key_path = config_dir / MASTER_KEY_FILE

    if not key_path.exists():
        raise FileNotFoundError(
            f"No master key found at {key_path}. Run `agentauth init` first."
        )

    data = json.loads(key_path.read_text())
    return bytes.fromhex(data["private_key"]), bytes.fromhex(data["public_key"])


def master_key_exists(config_dir: Path | None = None) -> bool:
    """Check if a master key already exists."""
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    return (config_dir / MASTER_KEY_FILE).exists()
