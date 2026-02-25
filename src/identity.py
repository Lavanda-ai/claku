#!/usr/bin/env python3
"""
Claku — Decentralized Agent Communication Platform
Core library: identity, messaging, channels, discovery over Waku.
"""

import json
import time
import hashlib
import os
import secrets
import base64
from pathlib import Path
from typing import Optional

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
    """Generate a new agent identity (simplified keypair)."""
    # Generate a 32-byte secret key
    secret = secrets.token_hex(32)
    # Derive a public key (simplified — hash of secret)
    pubkey = hashlib.sha256(bytes.fromhex(secret)).hexdigest()
    # X25519 key for encryption (simplified)
    x25519_secret = secrets.token_hex(32)
    x25519_pub = hashlib.sha256(bytes.fromhex(x25519_secret)).hexdigest()

    identity = {
        "name": name,
        "owner": owner,
        "pubkey": pubkey,
        "secret": secret,
        "x25519_pubkey": x25519_pub,
        "x25519_secret": x25519_secret,
        "capabilities": capabilities,
        "channels": ["#general"],
        "created": int(time.time()),
        "version": "claku/0.1.0"
    }
    return identity


def load_identity() -> Optional[dict]:
    """Load existing identity or return None."""
    if IDENTITY_FILE.exists():
        return json.loads(IDENTITY_FILE.read_text())
    return None


def save_identity(identity: dict):
    """Save identity to disk."""
    ensure_dir()
    IDENTITY_FILE.write_text(json.dumps(identity, indent=2))


def get_or_create_identity(name: str, owner: str, capabilities: list[str]) -> dict:
    """Load existing identity or create new one."""
    identity = load_identity()
    if identity is None:
        identity = generate_identity(name, owner, capabilities)
        save_identity(identity)
    return identity
