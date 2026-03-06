#!/usr/bin/env python3
"""
Claku — Agent Connection & Trust Manager.

Handles connection requests, trust levels, and auto-accept rules.
"""

import json
import time
from typing import Optional
from pathlib import Path

CLAKU_DIR = Path.home() / ".claku"
CONNECTIONS_FILE = CLAKU_DIR / "connections.json"

# Trust levels
UNKNOWN = 0
SEEN = 1
CONTACTED = 2
TRUSTED = 3
CIRCLE = 4

TRUST_NAMES = {
    UNKNOWN: "unknown",
    SEEN: "seen",
    CONTACTED: "contacted",
    TRUSTED: "trusted",
    CIRCLE: "circle",
}


class ConnectionManager:
    """Manages agent connections and trust levels."""

    def __init__(self) -> None:
        self.connections: dict[str, dict] = {}  # pubkey → connection info
        self.auto_rules: dict = {
            "accept_from_circles": [],
            "accept_capabilities": [],
            "require_trust_level": UNKNOWN,
            "require_human_approval": False,
        }
        self._load()

    def _load(self) -> None:
        if CONNECTIONS_FILE.exists():
            try:
                data = json.loads(CONNECTIONS_FILE.read_text())
                self.connections = data.get("connections", {})
                self.auto_rules = data.get("auto_rules", self.auto_rules)
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        CLAKU_DIR.mkdir(parents=True, exist_ok=True)
        CONNECTIONS_FILE.write_text(json.dumps({
            "connections": self.connections,
            "auto_rules": self.auto_rules,
        }, indent=2))

    def get_trust(self, pubkey: str) -> int:
        """Get trust level for an agent."""
        conn = self.connections.get(pubkey)
        return conn["trust"] if conn else UNKNOWN

    def set_trust(self, pubkey: str, level: int) -> None:
        """Set trust level for an agent."""
        if pubkey not in self.connections:
            self.connections[pubkey] = {
                "pubkey": pubkey,
                "trust": level,
                "name": "",
                "connected_at": int(time.time()),
            }
        else:
            self.connections[pubkey]["trust"] = level
        self._save()

    def on_agent_seen(self, pubkey: str, name: str, capabilities: list[str] = None) -> None:
        """Record that we've seen an agent's card."""
        if pubkey not in self.connections:
            self.connections[pubkey] = {
                "pubkey": pubkey,
                "name": name,
                "capabilities": capabilities or [],
                "trust": SEEN,
                "connected_at": int(time.time()),
            }
        else:
            self.connections[pubkey]["name"] = name
            if capabilities:
                self.connections[pubkey]["capabilities"] = capabilities
            if self.connections[pubkey]["trust"] < SEEN:
                self.connections[pubkey]["trust"] = SEEN
        self._save()

    def should_auto_accept(self, from_pubkey: str, from_caps: list[str] = None,
                           from_circles: list[str] = None) -> bool:
        """Check if a connection request should be auto-accepted."""
        if self.auto_rules.get("require_human_approval"):
            return False

        trust = self.get_trust(from_pubkey)
        min_trust = self.auto_rules.get("require_trust_level", UNKNOWN)
        if trust >= min_trust and min_trust > UNKNOWN:
            return True

        # Check circle membership
        accept_circles = self.auto_rules.get("accept_from_circles", [])
        if from_circles and accept_circles:
            if any(c in accept_circles for c in from_circles):
                return True

        # Check capabilities
        accept_caps = self.auto_rules.get("accept_capabilities", [])
        if from_caps and accept_caps:
            if any(c in accept_caps for c in from_caps):
                return True

        return False

    def accept_connection(self, pubkey: str, name: str) -> dict:
        """Accept a connection request."""
        if pubkey not in self.connections:
            self.connections[pubkey] = {
                "pubkey": pubkey,
                "name": name,
                "trust": CONTACTED,
                "connected_at": int(time.time()),
            }
        else:
            self.connections[pubkey]["trust"] = max(
                self.connections[pubkey]["trust"], CONTACTED
            )
        self._save()
        return self.connections[pubkey]

    def refuse_connection(self, pubkey: str) -> None:
        """Refuse a connection (keeps at current trust, doesn't elevate)."""
        pass  # No state change needed

    def revoke_trust(self, pubkey: str) -> None:
        """Revoke all trust for an agent."""
        if pubkey in self.connections:
            self.connections[pubkey]["trust"] = UNKNOWN
            self._save()

    def list_connections(self, min_trust: int = SEEN) -> list[dict]:
        """List connections at or above a trust level."""
        return [
            c for c in self.connections.values()
            if c.get("trust", 0) >= min_trust
        ]

    def promote_to_trusted(self, pubkey: str) -> None:
        """Promote an agent to TRUSTED (requires human approval)."""
        if pubkey in self.connections:
            self.connections[pubkey]["trust"] = TRUSTED
            self._save()

    def promote_to_circle(self, pubkey: str) -> None:
        """Promote an agent to CIRCLE trust level."""
        if pubkey in self.connections:
            self.connections[pubkey]["trust"] = CIRCLE
            self._save()
