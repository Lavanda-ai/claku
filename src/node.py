#!/usr/bin/env python3
"""
Claku — Agent Node
Handles discovery, channels, direct messages, and task management.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from .identity import (
    get_or_create_identity, load_identity, save_identity,
    CLAKU_DIR, DASHBOARD_FILE,
    DISCOVERY_TOPIC, CHANNEL_TOPIC, DM_TOPIC, TASK_TOPIC, ACK_TOPIC,
)
from .transport import WakuTransport
from .crypto import (
    encrypt_for_recipient, decrypt_from_sender,
    sign_message, verify_signature,
    hex_to_bytes,
)


class ClakuNode:
    """A Claku agent node — identity + transport + messaging."""

    def __init__(self, name: str, owner: str, capabilities: list[str],
                 waku_url: str = "http://localhost:8645"):
        self.transport = WakuTransport(waku_url)
        self.identity = get_or_create_identity(name, owner, capabilities)
        self.known_agents: dict[str, dict] = {}
        self.channels: set[str] = set(self.identity.get("channels", ["#general"]))
        self._ensure_subscribed()

    def _ensure_subscribed(self):
        """Subscribe to the pubsub topic."""
        self.transport.subscribe()

    def _log_dashboard(self, event_type: str, data: dict):
        """Append event to dashboard log for human visibility."""
        CLAKU_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "type": event_type,
            "agent": self.identity["name"],
            **data,
        }
        with open(DASHBOARD_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # --- Discovery ---

    def agent_card(self) -> dict:
        """Build this agent's public card."""
        return {
            "type": "agent_card",
            "name": self.identity["name"],
            "pubkey": self.identity["pubkey"],
            "owner": self.identity["owner"],
            "capabilities": self.identity["capabilities"],
            "channels": list(self.channels),
            "intro_bundle": {"x25519_pubkey": self.identity["x25519_pubkey"]},
            "version": self.identity["version"],
            "ts": int(time.time()),
        }

    def announce(self) -> bool:
        """Broadcast agent card to discovery topic."""
        card = self.agent_card()
        ok = self.transport.publish_json(DISCOVERY_TOPIC, card)
        if ok:
            self._log_dashboard("announce", {"card": card})
        return ok

    def discover(self) -> list[dict]:
        """Poll discovery topic for agent cards."""
        messages = self.transport.poll_json(DISCOVERY_TOPIC)
        agents = []
        for msg in messages:
            if msg.get("type") == "agent_card" and msg.get("pubkey") != self.identity["pubkey"]:
                self.known_agents[msg["pubkey"]] = msg
                agents.append(msg)
                self._log_dashboard("discovered", {
                    "remote_agent": msg["name"],
                    "pubkey": msg["pubkey"][:16] + "...",
                })
        return agents

    # --- Channels ---

    def join_channel(self, channel: str):
        """Join a channel."""
        if not channel.startswith("#"):
            channel = f"#{channel}"
        self.channels.add(channel)
        self.identity["channels"] = list(self.channels)
        save_identity(self.identity)
        self._log_dashboard("join_channel", {"channel": channel})

    def leave_channel(self, channel: str):
        """Leave a channel."""
        self.channels.discard(channel)
        self.identity["channels"] = list(self.channels)
        save_identity(self.identity)

    def send_channel(self, channel: str, text: str) -> bool:
        """Send a signed message to a channel."""
        if not channel.startswith("#"):
            channel = f"#{channel}"
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "channel_msg",
            "channel": channel,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "text": text,
            "msg_id": msg_id,
            "ts": int(time.time()),
        }
        # Sign the message content
        sign_data = f"{msg_id}:{channel}:{text}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        msg["signature"] = sign_message(sign_data, ed_priv)

        ok = self.transport.publish_json(CHANNEL_TOPIC(channel.lstrip("#")), msg)
        if ok:
            self._log_dashboard("channel_send", {"channel": channel, "text": text})
        return ok

    def poll_channel(self, channel: str) -> list[dict]:
        """Poll a channel for new messages, verifying signatures."""
        if not channel.startswith("#"):
            channel = f"#{channel}"
        messages = self.transport.poll_json(CHANNEL_TOPIC(channel.lstrip("#")))
        verified = []
        for msg in messages:
            if msg.get("type") != "channel_msg":
                continue
            # Verify signature if present
            sig = msg.get("signature")
            pubkey_hex = msg.get("from_pubkey", "")
            msg_id = msg.get("msg_id", "")
            text = msg.get("text", "")
            if sig and pubkey_hex:
                sign_data = f"{msg_id}:{msg.get('channel', '')}:{text}".encode("utf-8")
                try:
                    pub = hex_to_bytes(pubkey_hex)
                    msg["_verified"] = verify_signature(sign_data, sig, pub)
                except Exception:
                    msg["_verified"] = False
            else:
                msg["_verified"] = False
            verified.append(msg)
            self._log_dashboard("channel_recv", {
                "channel": channel,
                "from": msg.get("from", "unknown"),
                "text": text,
                "verified": msg["_verified"],
            })
        return verified

    # --- Direct Messages ---

    def send_dm(self, to_pubkey: str, text: str) -> bool:
        """Send an E2E encrypted direct message to another agent."""
        # Look up recipient's X25519 public key from known agents
        recipient = self.known_agents.get(to_pubkey, {})
        x25519_pub_hex = recipient.get("intro_bundle", {}).get("x25519_pubkey", "")
        if not x25519_pub_hex:
            # Fallback: try to use to_pubkey as x25519 key directly
            x25519_pub_hex = to_pubkey

        try:
            their_x25519 = hex_to_bytes(x25519_pub_hex)
            my_x25519 = hex_to_bytes(self.identity["x25519_secret"])
            encrypted_text = encrypt_for_recipient(
                text.encode("utf-8"), my_x25519, their_x25519
            )
        except Exception as e:
            # Fall back to plaintext if encryption fails
            encrypted_text = None

        msg = {
            "type": "dm",
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "from_x25519": self.identity["x25519_pubkey"],
            "to_pubkey": to_pubkey,
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }

        if encrypted_text:
            msg["encrypted"] = True
            msg["ciphertext"] = encrypted_text
        else:
            msg["encrypted"] = False
            msg["text"] = text

        ok = self.transport.publish_json(DM_TOPIC(to_pubkey), msg)
        if ok:
            to_name = recipient.get("name", to_pubkey[:16])
            self._log_dashboard("dm_send", {
                "to": to_name, "text": text[:50],
                "encrypted": msg["encrypted"],
            })
        return ok

    def poll_dms(self) -> list[dict]:
        """Poll for direct messages, decrypting E2E encrypted ones."""
        messages = self.transport.poll_json(DM_TOPIC(self.identity["pubkey"]))
        dms = []
        for msg in messages:
            if msg.get("type") != "dm":
                continue
            if msg.get("to_pubkey") != self.identity["pubkey"]:
                continue

            if msg.get("encrypted") and msg.get("ciphertext"):
                sender_x25519 = msg.get("from_x25519", "")
                try:
                    their_x25519 = hex_to_bytes(sender_x25519)
                    my_x25519 = hex_to_bytes(self.identity["x25519_secret"])
                    plaintext = decrypt_from_sender(
                        msg["ciphertext"], my_x25519, their_x25519
                    )
                    msg["text"] = plaintext.decode("utf-8")
                    msg["_decrypted"] = True
                except Exception:
                    msg["text"] = "[decryption failed]"
                    msg["_decrypted"] = False
            else:
                msg["_decrypted"] = False

            self._log_dashboard("dm_recv", {
                "from": msg.get("from", "unknown"),
                "text": msg.get("text", "")[:50],
                "encrypted": msg.get("encrypted", False),
            })
            dms.append(msg)
        return dms

    # --- Tasks ---

    def send_task(self, to_pubkey: str, description: str, task_type: str = "general") -> str:
        """Send a task request to another agent. Returns task_id."""
        task_id = str(uuid.uuid4())
        msg = {
            "type": "task_request",
            "task_id": task_id,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "to_pubkey": to_pubkey,
            "description": description,
            "task_type": task_type,
            "status": "pending",
            "ts": int(time.time()),
        }
        ok = self.transport.publish_json(TASK_TOPIC(task_id), msg)
        if ok:
            to_name = self.known_agents.get(to_pubkey, {}).get("name", to_pubkey[:16])
            self._log_dashboard("task_send", {
                "to": to_name, "task_id": task_id, "description": description
            })
        return task_id

    def respond_task(self, task_id: str, result: str, status: str = "completed") -> bool:
        """Respond to a task with results."""
        msg = {
            "type": "task_response",
            "task_id": task_id,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "result": result,
            "status": status,
            "ts": int(time.time()),
        }
        ok = self.transport.publish_json(TASK_TOPIC(task_id), msg)
        if ok:
            self._log_dashboard("task_respond", {
                "task_id": task_id, "status": status, "result": result[:100]
            })
        return ok

    def poll_tasks(self) -> list[dict]:
        """Poll for incoming task requests."""
        # Poll all task topics — in practice, agents listen on their DM topic
        # for task notifications. This is a simplified version.
        messages = self.transport.poll_json(DM_TOPIC(self.identity["pubkey"]))
        tasks = [m for m in messages if m.get("type") == "task_request"]
        for t in tasks:
            self._log_dashboard("task_recv", {
                "from": t.get("from", "unknown"),
                "task_id": t.get("task_id", ""),
                "description": t.get("description", ""),
            })
        return tasks

    # --- Run Loop ---

    def run_once(self) -> dict:
        """Single poll cycle: discover, check channels, check DMs, check tasks."""
        results = {
            "discovered": self.discover(),
            "dms": self.poll_dms(),
            "tasks": self.poll_tasks(),
            "channels": {},
        }
        for ch in self.channels:
            msgs = self.poll_channel(ch)
            if msgs:
                results["channels"][ch] = msgs
        return results
