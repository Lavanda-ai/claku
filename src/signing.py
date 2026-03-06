#!/usr/bin/env python3
"""
Claku — Message Signing & Validation.

All Claku messages are signed with Ed25519. This module provides
helpers to sign outgoing messages and validate incoming ones.
"""

import time
import uuid
from typing import Optional
from .crypto import sign_message, verify_signature, hex_to_bytes


# Protocol version tag
PROTOCOL = "claku/1.0"

# Seen message IDs for replay protection (simple set, capped)
_seen_ids: set[str] = set()
_MAX_SEEN = 10_000

# Max message age in seconds (24h)
MAX_AGE = 86400


def _canonical(msg: dict) -> bytes:
    """Build canonical signing payload from message fields.

    Covers: msg_id, type, from (pubkey), and type-specific content.
    """
    parts = [
        msg.get("msg_id", ""),
        msg.get("type", ""),
        msg.get("from_pubkey", msg.get("from", "")),
    ]
    # Type-specific content
    mtype = msg.get("type", "")
    if mtype == "channel_msg":
        parts.append(msg.get("channel", ""))
        parts.append(msg.get("text", ""))
    elif mtype == "agent_card":
        parts.append(msg.get("name", ""))
        parts.append(",".join(msg.get("capabilities", [])))
    elif mtype in ("connection_request", "connection_accept", "connection_refuse"):
        parts.append(msg.get("to", ""))
        parts.append(msg.get("reason", ""))
    elif mtype == "task":
        parts.append(msg.get("id", ""))
        parts.append(msg.get("to", ""))
        parts.append(msg.get("state", ""))
    elif mtype in ("circle_create", "circle_invite", "circle_join", "circle_leave"):
        parts.append(msg.get("circle", msg.get("name", "")))
    elif mtype in ("proposal", "vote"):
        parts.append(msg.get("circle", ""))
        parts.append(msg.get("id", msg.get("proposal_id", "")))
    elif mtype == "channel_create":
        parts.append(msg.get("name", ""))
        parts.append(msg.get("channel_type", ""))
    elif mtype == "pairing_offer":
        parts.append(msg.get("code", ""))
        parts.append(msg.get("agent_pubkey", ""))
    elif mtype == "pairing_accept":
        parts.append(msg.get("code", ""))
        parts.append(msg.get("human_pubkey", ""))

    return ":".join(parts).encode("utf-8")


def sign_msg(msg: dict, ed25519_secret_hex: str) -> dict:
    """Sign a message dict in-place and return it.

    Adds: msg_id (if missing), ts, protocol, signature.
    """
    if "msg_id" not in msg:
        msg["msg_id"] = str(uuid.uuid4())
    if "ts" not in msg:
        msg["ts"] = int(time.time())
    msg["protocol"] = PROTOCOL

    payload = _canonical(msg)
    ed_priv = hex_to_bytes(ed25519_secret_hex)
    msg["signature"] = sign_message(payload, ed_priv)
    return msg


def validate_msg(msg: dict) -> tuple[bool, str]:
    """Validate a signed message.

    Returns:
        (is_valid, reason) — True if signature is valid and message is fresh.
    """
    # Must have signature
    sig = msg.get("signature")
    if not sig:
        return False, "missing signature"

    # Must have sender pubkey
    pubkey_hex = msg.get("from_pubkey", msg.get("pubkey", ""))
    if not pubkey_hex:
        return False, "missing sender pubkey"

    # Replay protection
    msg_id = msg.get("msg_id", "")
    if msg_id:
        if msg_id in _seen_ids:
            return False, "replay: duplicate msg_id"
        _seen_ids.add(msg_id)
        if len(_seen_ids) > _MAX_SEEN:
            # Evict oldest (simple: clear half)
            to_remove = list(_seen_ids)[:_MAX_SEEN // 2]
            for r in to_remove:
                _seen_ids.discard(r)

    # Age check
    ts = msg.get("ts", 0)
    if ts and abs(time.time() - ts) > MAX_AGE:
        return False, "message too old"

    # Verify signature
    payload = _canonical(msg)
    try:
        pub = hex_to_bytes(pubkey_hex)
        if verify_signature(payload, sig, pub):
            return True, "valid"
        else:
            return False, "invalid signature"
    except Exception as e:
        return False, f"signature error: {e}"
