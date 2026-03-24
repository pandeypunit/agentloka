"""Tests for master key generation and agent key derivation."""

import json
import tempfile
from pathlib import Path

from agentauth.keys.master import (
    generate_master_key,
    load_master_key,
    master_key_exists,
    save_master_key,
)
from agentauth.keys.derivation import derive_agent_key, sign_message, verify_signature


def test_generate_master_key():
    private_key, public_key = generate_master_key()
    assert len(private_key) == 32
    assert len(public_key) == 32
    assert private_key != public_key


def test_generate_unique_keys():
    key1 = generate_master_key()
    key2 = generate_master_key()
    assert key1[0] != key2[0]  # Different private keys
    assert key1[1] != key2[1]  # Different public keys


def test_save_and_load_master_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        private_key, public_key = generate_master_key()

        save_master_key(private_key, public_key, config_dir)
        loaded_private, loaded_public = load_master_key(config_dir)

        assert loaded_private == private_key
        assert loaded_public == public_key


def test_master_key_file_permissions():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        private_key, public_key = generate_master_key()
        key_path = save_master_key(private_key, public_key, config_dir)

        # Owner read/write only (0o600)
        mode = key_path.stat().st_mode & 0o777
        assert mode == 0o600


def test_master_key_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        assert not master_key_exists(config_dir)

        private_key, public_key = generate_master_key()
        save_master_key(private_key, public_key, config_dir)
        assert master_key_exists(config_dir)


def test_load_missing_key_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        try:
            load_master_key(config_dir)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


def test_derive_agent_key():
    master_private, _ = generate_master_key()
    agent_private, agent_public = derive_agent_key(master_private, "test_agent")

    assert len(agent_private) == 32
    assert len(agent_public) == 32
    assert agent_private != master_private


def test_derivation_is_deterministic():
    master_private, _ = generate_master_key()

    key1 = derive_agent_key(master_private, "my_agent")
    key2 = derive_agent_key(master_private, "my_agent")

    assert key1[0] == key2[0]  # Same private key
    assert key1[1] == key2[1]  # Same public key


def test_different_names_produce_different_keys():
    master_private, _ = generate_master_key()

    key1 = derive_agent_key(master_private, "agent_one")
    key2 = derive_agent_key(master_private, "agent_two")

    assert key1[0] != key2[0]
    assert key1[1] != key2[1]


def test_different_masters_produce_different_keys():
    master1, _ = generate_master_key()
    master2, _ = generate_master_key()

    key1 = derive_agent_key(master1, "same_name")
    key2 = derive_agent_key(master2, "same_name")

    assert key1[0] != key2[0]
    assert key1[1] != key2[1]


def test_sign_and_verify():
    master_private, _ = generate_master_key()
    agent_private, agent_public = derive_agent_key(master_private, "signer_agent")

    message = b"register agent: signer_agent"
    signature = sign_message(agent_private, message)

    assert len(signature) == 64
    assert verify_signature(agent_public, message, signature)


def test_verify_wrong_message_fails():
    master_private, _ = generate_master_key()
    agent_private, agent_public = derive_agent_key(master_private, "signer_agent")

    signature = sign_message(agent_private, b"original message")
    assert not verify_signature(agent_public, b"tampered message", signature)


def test_verify_wrong_key_fails():
    master_private, _ = generate_master_key()
    key1_private, _ = derive_agent_key(master_private, "agent_one")
    _, key2_public = derive_agent_key(master_private, "agent_two")

    message = b"some message"
    signature = sign_message(key1_private, message)

    # Verify with wrong public key should fail
    assert not verify_signature(key2_public, message, signature)
