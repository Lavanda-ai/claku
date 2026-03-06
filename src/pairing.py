#!/usr/bin/env python3
"""
Claku — Human-Agent Pairing.

Secure pairing between a human (dashboard/CLI) and an agent using
a 6-digit code + ECDH key exchange.
"""

import os
import json
import time
import random
import string
from typing import Optional
from pathlib import Path

from .crypto import (
    generate_x25519_keypair,
    ecdh_shared_secret,
    bytes_to_hex,
    hex_to_bytes,
)

CLAKU_DIR = Path.home() / ".claku"
PAIRINGS_FILE = CLAKU_DIR / "pairings.json"

# Pairing code settings
CODE_LENGTH = 6
CODE_EXPIRY = 300  # 5 minutes


def generate_pairing_code() -> str:
    """Generate a random 6-digit pairing code."""
    return "".join(random.choices(string.digits, k=CODE_LENGTH))


class PairingManager:
    """Manages human-agent pairings."""

    def __init__(self) -> None:
        self.pairings: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}  # code → offer
        self._load()

    def _load(self) -> None:
        """Load saved pairings and pending offers from disk."""
        if PAIRINGS_FILE.exists():
            try:
                data = json.loads(PAIRINGS_FILE.read_text())
                self.pairings = data.get("pairings", {})
                self.pending = data.get("pending", {})
            except (json.JSONDecodeError, OSError):
                self.pairings = {}
                self.pending = {}

    def _save(self) -> None:
        """Persist pairings and pending offers to disk."""
        CLAKU_DIR.mkdir(parents=True, exist_ok=True)
        PAIRINGS_FILE.write_text(json.dumps({
            "pairings": self.pairings,
            "pending": self.pending
        }, indent=2))

    def create_offer(self, agent_pubkey: str, agent_x25519_pub: str) -> dict:
        """Create a pairing offer with a 6-digit code.

        Returns:
            Dict with code, agent_pubkey, ephemeral x25519 pubkey, expires.
        """
        code = generate_pairing_code()

        # Generate ephemeral keypair for this pairing
        eph_priv, eph_pub = generate_x25519_keypair()

        offer = {
            "code": code,
            "agent_pubkey": agent_pubkey,
            "agent_x25519_pub": agent_x25519_pub,
            "eph_private": bytes_to_hex(eph_priv),
            "eph_public": bytes_to_hex(eph_pub),
            "created": int(time.time()),
            "expires": int(time.time()) + CODE_EXPIRY,
        }

        self.pending[code] = offer
        return {
            "code": code,
            "agent_pubkey": agent_pubkey,
            "eph_public": bytes_to_hex(eph_pub),
            "expires": offer["expires"],
        }

    def accept_offer(self, code: str, human_x25519_pub_hex: str) -> Optional[dict]:
        """Accept a pairing offer using the code.

        Args:
            code: The 6-digit pairing code.
            human_x25519_pub_hex: Human's X25519 public key (hex).

        Returns:
            Pairing dict with shared_secret, or None if code invalid/expired.
        """
        offer = self.pending.get(code)
        if not offer:
            return None

        # Check expiry
        if time.time() > offer["expires"]:
            del self.pending[code]
            return None

        # Derive shared secret
        eph_priv = hex_to_bytes(offer["eph_private"])
        human_pub = hex_to_bytes(human_x25519_pub_hex)
        shared = ecdh_shared_secret(eph_priv, human_pub)

        pairing = {
            "agent_pubkey": offer["agent_pubkey"],
            "human_x25519_pub": human_x25519_pub_hex,
            "shared_secret": bytes_to_hex(shared),
            "paired_at": int(time.time()),
        }

        # Store and clean up
        self.pairings[human_x25519_pub_hex] = pairing
        del self.pending[code]
        self._save()

        return pairing

    def is_paired(self, human_x25519_pub_hex: str) -> bool:
        """Check if a human is paired."""
        return human_x25519_pub_hex in self.pairings

    def get_pairing(self, human_x25519_pub_hex: str) -> Optional[dict]:
        """Get pairing info for a human."""
        return self.pairings.get(human_x25519_pub_hex)

    def revoke(self, human_x25519_pub_hex: str) -> bool:
        """Revoke a pairing."""
        if human_x25519_pub_hex in self.pairings:
            del self.pairings[human_x25519_pub_hex]
            self._save()
            return True
        return False

    def list_pairings(self) -> list[dict]:
        """List all active pairings."""
        return list(self.pairings.values())

    def cleanup_expired(self) -> int:
        """Remove expired pending offers. Returns count removed."""
        now = time.time()
        expired = [c for c, o in self.pending.items() if now > o["expires"]]
        for c in expired:
            del self.pending[c]
        return len(expired)
