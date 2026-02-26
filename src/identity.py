#!/usr/bin/env python3
"""
Claku — Decentralized Agent Communication Platform
Core library: identity, messaging, channels, discovery over Waku.
"""

import json
import time
import os
import secrets
from pathlib import Path
from typing import Optional

from .crypto import (
    generate_x25519_keypair, generate_ed25519_keypair,
    bytes_to_hex, hex_to_bytes,
)

CLAKU_DIR = Path.home() / ".claku"
IDENTITY_FILE = CLAKU_DIR / "identity.json"
DASHBOARD_FILE = CLAKU_DIR / "dashboard.jsonl"
CONFIG_FILE = CLAKU_DIR / "config.json"

# Waku content topic prefixes
TOPIC_PREFIX = "/claku/1"
DISCOVERY_TOPIC = f"{TOPIC_PREFIX}/discovery/proto"
CHANNEL_TOPIC = lambda name: f"{TOPIC_PREFIX}/channel/{name}/proto"
DM_TOPIC = lambda pubkey: f"{TOPIC_PREFIX}/dm/{pubkey[:16]}/proto"
TASK_TOPIC = lambda task_id: f"{TOPIC_PREFIX}/task/{task_id}/proto"
ACK_TOPIC = lambda msg_id: f"{TOPIC_PREFIX}/ack/{msg_id}/proto"

# Default pubsub topic for static sharding
PUBSUB_TOPIC = "/waku/2/rs/0/0"


def ensure_dir():
    """Create claku directory if needed."""
    CLAKU_DIR.mkdir(parents=True, exist_ok=True)


def generate_identity(name: str, owner: str, capabilities: list[str]) -> dict:
    """Generate a new agent identity with real Ed25519 + X25519 keys."""
    # Ed25519 for signing / identity
    ed_priv, ed_pub = generate_ed25519_keypair()
    # X25519 for encryption (DMs)
    x_priv, x_pub = generate_x25519_keypair()

    identity = {
        "name": name,
        "owner": owner,
        "pubkey": bytes_to_hex(ed_pub),
        "secret": bytes_to_hex(ed_priv),
        "x25519_pubkey": bytes_to_hex(x_pub),
        "x25519_secret": bytes_to_hex(x_priv),
        "capabilities": capabilities,
        "channels": ["#general"],
        "created": int(time.time()),
        "version": "claku/0.2.0"
    }
    return identity


def load_identity() -> Optional[dict]:
    """Load existing identity or return None. Handles corrupt files."""
    if not IDENTITY_FILE.exists():
        return None
    try:
        data = json.loads(IDENTITY_FILE.read_text())
        # Validate required fields
        required = ("name", "pubkey", "secret", "x25519_pubkey", "x25519_secret")
        if not all(k in data for k in required):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_identity(identity: dict):
    """Save identity to disk."""
    ensure_dir()
    IDENTITY_FILE.write_text(json.dumps(identity, indent=2))


def get_or_create_identity(name: str, owner: str, capabilities: list[str],
                           force: bool = False) -> dict:
    """Load existing identity or create new one."""
    if not force:
        identity = load_identity()
        if identity is not None:
            return identity
    identity = generate_identity(name, owner, capabilities)
    save_identity(identity)
    return identity
