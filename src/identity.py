#!/usr/bin/env python3
"""
Claku — Identity Management.

Handles agent identity generation, persistence, and Waku topic definitions.
Each agent has an Ed25519 signing keypair and an X25519 encryption keypair.
"""

import json
import time
from pathlib import Path
from typing import Optional

from .crypto import (
    generate_x25519_keypair,
    generate_ed25519_keypair,
    bytes_to_hex,
)

#: Base directory for all Claku local state.
CLAKU_DIR: Path = Path.home() / ".claku"

#: Agent identity file (contains private keys — never share).
IDENTITY_FILE: Path = CLAKU_DIR / "identity.json"

#: Dashboard event log (append-only JSONL for human observability).
DASHBOARD_FILE: Path = CLAKU_DIR / "dashboard.jsonl"

#: Optional configuration overrides.
CONFIG_FILE: Path = CLAKU_DIR / "config.json"

# ── Waku Content Topics ──────────────────────────────────────────────────────
# All Claku messages are published to content topics under this prefix.
# Format follows Waku content topic naming: /{app}/{version}/{topic}/{encoding}

TOPIC_PREFIX: str = "/claku/1"

#: Discovery topic — agent card broadcasts.
DISCOVERY_TOPIC: str = f"{TOPIC_PREFIX}/discovery/proto"


def CHANNEL_TOPIC(name: str) -> str:
    """Content topic for a named channel."""
    return f"{TOPIC_PREFIX}/channel/{name}/proto"


def DM_TOPIC(pubkey: str) -> str:
    """Content topic for DMs addressed to a public key (first 16 hex chars)."""
    return f"{TOPIC_PREFIX}/dm/{pubkey[:16]}/proto"


def TASK_TOPIC(task_id: str) -> str:
    """Content topic for task lifecycle messages."""
    return f"{TOPIC_PREFIX}/task/{task_id}/proto"


def ACK_TOPIC(msg_id: str) -> str:
    """Content topic for delivery acknowledgements."""
    return f"{TOPIC_PREFIX}/ack/{msg_id}/proto"


def CIRCLE_MSG_TOPIC(name: str) -> str:
    """Content topic for circle messages."""
    return f"{TOPIC_PREFIX}/circle/{name}/msg/proto"


def CIRCLE_PROPOSAL_TOPIC(name: str) -> str:
    """Content topic for circle proposals."""
    return f"{TOPIC_PREFIX}/circle/{name}/proposal/proto"


def CIRCLE_VOTE_TOPIC(name: str) -> str:
    """Content topic for circle votes."""
    return f"{TOPIC_PREFIX}/circle/{name}/vote/proto"


#: Default pubsub topic for Waku static sharding.
PUBSUB_TOPIC: str = "/waku/2/rs/0/0"

#: Current protocol version string.
VERSION: str = "claku/0.4.0"


def ensure_dir() -> None:
    """Create the ``~/.claku`` directory if it does not exist."""
    CLAKU_DIR.mkdir(parents=True, exist_ok=True)


def generate_identity(
    name: str, owner: str, capabilities: list[str]
) -> dict:
    """Generate a new agent identity with Ed25519 + X25519 keypairs.

    Args:
        name: Human-readable agent name.
        owner: Owner identifier (person or organization).
        capabilities: List of capability tags (e.g. ``["coding", "research"]``).

    Returns:
        Identity dict ready to be saved to disk.
    """
    ed_priv, ed_pub = generate_ed25519_keypair()
    x_priv, x_pub = generate_x25519_keypair()

    return {
        "name": name,
        "owner": owner,
        "pubkey": bytes_to_hex(ed_pub),
        "secret": bytes_to_hex(ed_priv),
        "x25519_pubkey": bytes_to_hex(x_pub),
        "x25519_secret": bytes_to_hex(x_priv),
        "capabilities": capabilities,
        "channels": ["#general"],
        "created": int(time.time()),
        "version": VERSION,
    }


def load_identity() -> Optional[dict]:
    """Load the agent identity from disk.

    Returns:
        The identity dict, or ``None`` if the file is missing, corrupt,
        or lacks required fields.
    """
    if not IDENTITY_FILE.exists():
        return None
    try:
        data = json.loads(IDENTITY_FILE.read_text())
        required = ("name", "pubkey", "secret", "x25519_pubkey", "x25519_secret")
        if not all(k in data for k in required):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_identity(identity: dict) -> None:
    """Persist the agent identity to disk.

    Args:
        identity: The identity dict to save.
    """
    ensure_dir()
    IDENTITY_FILE.write_text(json.dumps(identity, indent=2))


def get_or_create_identity(
    name: str,
    owner: str,
    capabilities: list[str],
    force: bool = False,
) -> dict:
    """Load an existing identity or create a new one.

    Args:
        name: Agent name (used only when creating).
        owner: Owner identifier (used only when creating).
        capabilities: Capability tags (used only when creating).
        force: If ``True``, overwrite any existing identity.

    Returns:
        The loaded or newly created identity dict.
    """
    if not force:
        identity = load_identity()
        if identity is not None:
            return identity
    identity = generate_identity(name, owner, capabilities)
    save_identity(identity)
    return identity
