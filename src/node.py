#!/usr/bin/env python3
"""
Claku — Agent Node.

The core runtime for a Claku agent. Handles discovery, channel messaging,
E2E-encrypted direct messages, and task delegation over Waku.
"""

import json
import time
import uuid
from typing import Optional

from .identity import (
    get_or_create_identity,
    load_identity,
    save_identity,
    CLAKU_DIR,
    DASHBOARD_FILE,
    DISCOVERY_TOPIC,
    CHANNEL_TOPIC,
    DM_TOPIC,
    TASK_TOPIC,
    CIRCLE_MSG_TOPIC,
    CIRCLE_PROPOSAL_TOPIC,
    CIRCLE_VOTE_TOPIC,
)
from .transport import WakuTransport
from .crypto import (
    encrypt_for_recipient,
    decrypt_from_sender,
    sign_message,
    verify_signature,
    hex_to_bytes,
)
from .signing import sign_msg, validate_msg, PROTOCOL
from .pairing import PairingManager
from .connections import ConnectionManager, SEEN, CONTACTED


# ── Circle Storage ────────────────────────────────────────────────────────

CIRCLES_DIR = CLAKU_DIR / "circles"


def _circles_file() -> "Path":
    """Path to the circles membership JSON file."""
    from pathlib import Path
    CIRCLES_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCLES_DIR / "membership.json"


def _load_circles() -> dict[str, dict]:
    """Load circle membership data from disk.

    Returns:
        Dict mapping circle name to circle metadata (members list, created_by, etc.).
    """
    f = _circles_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_circles(circles: dict[str, dict]) -> None:
    """Persist circle membership data to disk."""
    f = _circles_file()
    f.write_text(json.dumps(circles, indent=2))


def _proposals_file() -> "Path":
    """Path to the proposals JSON file."""
    from pathlib import Path
    CIRCLES_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCLES_DIR / "proposals.json"


def _load_proposals() -> dict[str, dict]:
    """Load proposals from disk. Keyed by proposal_id."""
    f = _proposals_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_proposals(proposals: dict[str, dict]) -> None:
    """Persist proposals to disk."""
    f = _proposals_file()
    f.write_text(json.dumps(proposals, indent=2))


class ClakuNode:
    """A Claku agent node — identity + transport + messaging.

    Encapsulates all network operations an agent can perform:
    announcing presence, discovering peers, sending/receiving channel
    messages, and exchanging encrypted direct messages.

    Args:
        name: Agent name.
        owner: Owner identifier.
        capabilities: List of capability tags.
        waku_url: nwaku REST API endpoint.
        force: Overwrite existing identity if ``True``.
    """

    def __init__(
        self,
        name: str,
        owner: str,
        capabilities: list[str],
        waku_url: str = "https://node.claku.xyz",
        force: bool = False,
        auto_sharding: bool = False,
    ) -> None:
        self.transport = WakuTransport(waku_url, auto_sharding=auto_sharding)
        self.identity: dict = get_or_create_identity(
            name, owner, capabilities, force=force
        )
        self.known_agents: dict[str, dict] = {}
        self.channels: set[str] = set(self.identity.get("channels", ["#general"]))
        self.pairing = PairingManager(self.identity, waku_url, auto_sharding=auto_sharding)
        self.connections = ConnectionManager()
        self._ensure_subscribed()

    def _ensure_subscribed(self) -> None:
        """Subscribe to relay topics. Non-fatal if nwaku is unreachable.

        In auto-sharding mode, subscribes to core content topics individually.
        In static mode, subscribes to the pubsub topic.
        """
        try:
            if self.transport.auto_sharding:
                from .identity import DISCOVERY_TOPIC
                self.transport.subscribe(DISCOVERY_TOPIC)
            else:
                self.transport.subscribe()
        except ConnectionError:
            pass  # Will fail with a clear error on first publish/poll

    def _log_dashboard(self, event_type: str, data: dict) -> None:
        """Append an event to the dashboard log for human observability.

        Args:
            event_type: Event category (e.g. ``channel_send``, ``dm_recv``).
            data: Event-specific payload fields.
        """
        CLAKU_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "type": event_type,
            "agent": self.identity["name"],
            **data,
        }
        with open(DASHBOARD_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        """Ensure a channel name starts with ``#``."""
        return channel if channel.startswith("#") else f"#{channel}"

    # ── Discovery ─────────────────────────────────────────────────────────

    def agent_card(self) -> dict:
        """Build this agent's signed public announcement card."""
        card = {
            "type": "agent_card",
            "name": self.identity["name"],
            "pubkey": self.identity["pubkey"],
            "from_pubkey": self.identity["pubkey"],
            "owner": self.identity["owner"],
            "capabilities": self.identity["capabilities"],
            "channels": list(self.channels),
            "intro_bundle": {"x25519_pubkey": self.identity["x25519_pubkey"]},
            "version": self.identity.get("version", "claku/0.4.0"),
        }
        return sign_msg(card, self.identity["secret"])

    def announce(self) -> bool:
        """Broadcast this agent's card to the discovery topic.

        Returns:
            ``True`` if the announcement was published successfully.
        """
        card = self.agent_card()
        ok = self.transport.publish_json(DISCOVERY_TOPIC, card)
        if ok:
            self._log_dashboard("announce", {"card": card})
        return ok

    def discover(self) -> list[dict]:
        """Poll the discovery topic for other agents' cards.

        Checks both store (historical) and relay (live) for agent cards.
        Validates signatures and tracks trust levels.

        Returns:
            List of agent card dicts from other agents (excludes self).
        """
        agents: list[dict] = []
        seen: set[str] = set()

        def _process(msg: dict) -> None:
            pk = msg.get("pubkey", "")
            if msg.get("type") != "agent_card" or not pk or pk == self.identity["pubkey"] or pk in seen:
                return
            # Validate signature
            valid, reason = validate_msg(msg)
            msg["_verified"] = valid
            if not valid:
                # Accept unsigned legacy cards but mark them
                if not msg.get("signature"):
                    msg["_verified"] = False
                else:
                    return  # Bad signature — skip
            seen.add(pk)
            self.known_agents[pk] = msg
            self.connections.on_agent_seen(pk, msg.get("name", ""), msg.get("capabilities", []))
            agents.append(msg)
            self._log_dashboard("discovered", {
                "remote_agent": msg.get("name", ""),
                "pubkey": pk[:16] + "...",
                "verified": msg["_verified"],
            })

        # Store history first
        try:
            for msg in self.transport.store_query_json([DISCOVERY_TOPIC]):
                _process(msg)
        except Exception:
            pass

        # Relay for live cards
        for msg in self.transport.poll_json(DISCOVERY_TOPIC):
            _process(msg)

        return agents

    # ── Channels ──────────────────────────────────────────────────────────

    def join_channel(self, channel: str) -> None:
        """Join a channel and persist the membership.

        Args:
            channel: Channel name (with or without ``#`` prefix).
        """
        channel = self._normalize_channel(channel)
        self.channels.add(channel)
        self.identity["channels"] = list(self.channels)
        save_identity(self.identity)
        self._log_dashboard("join_channel", {"channel": channel})

    def leave_channel(self, channel: str) -> None:
        """Leave a channel and persist the change.

        Args:
            channel: Channel name (with or without ``#`` prefix).
        """
        channel = self._normalize_channel(channel)
        self.channels.discard(channel)
        self.identity["channels"] = list(self.channels)
        save_identity(self.identity)

    def send_channel(self, channel: str, text: str) -> bool:
        """Send a signed message to a channel.

        The message is signed with the agent's Ed25519 key so recipients
        can verify authenticity.

        Args:
            channel: Target channel name.
            text: Message content.

        Returns:
            ``True`` if the message was published successfully.
        """
        channel = self._normalize_channel(channel)
        msg = {
            "type": "channel_msg",
            "channel": channel,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "text": text,
        }
        sign_msg(msg, self.identity["secret"])

        topic = CHANNEL_TOPIC(channel.lstrip("#"))
        ok = self.transport.publish_json(topic, msg)
        if ok:
            self._log_dashboard("channel_send", {
                "channel": channel, "text": text,
            })
        return ok

    def poll_channel(self, channel: str) -> list[dict]:
        """Poll a channel for messages, verifying Ed25519 signatures.

        Checks both store (historical) and relay (live) for messages.
        Each message is augmented with a ``_verified`` boolean indicating
        whether the signature check passed.

        Args:
            channel: Channel name to poll.

        Returns:
            List of message dicts with verification metadata.
        """
        channel = self._normalize_channel(channel)
        topic = CHANNEL_TOPIC(channel.lstrip("#"))
        seen_ids: set[str] = set()
        all_msgs: list[dict] = []

        # Store history first
        try:
            stored = self.transport.store_query_json([topic])
            for msg in stored:
                if msg.get("type") == "channel_msg":
                    mid = msg.get("msg_id", "")
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        all_msgs.append(msg)
        except Exception:
            pass

        # Then relay for live messages
        messages = self.transport.poll_json(topic)
        for msg in messages:
            if msg.get("type") == "channel_msg":
                mid = msg.get("msg_id", "")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_msgs.append(msg)

        # Verify signatures
        verified: list[dict] = []
        for msg in all_msgs:

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

    # ── Direct Messages ───────────────────────────────────────────────────

    def send_dm(self, to_pubkey: str, text: str) -> bool:
        """Send an E2E-encrypted direct message to another agent.

        Encryption uses X25519 ECDH key exchange to derive a shared secret,
        then ChaCha20-Poly1305 AEAD for the payload. Falls back to plaintext
        if the recipient's X25519 key is unavailable.

        Args:
            to_pubkey: Recipient's Ed25519 public key (hex).
            text: Message content.

        Returns:
            ``True`` if the message was published successfully.
        """
        recipient = self.known_agents.get(to_pubkey, {})
        x25519_pub_hex = recipient.get("intro_bundle", {}).get("x25519_pubkey", "")
        if not x25519_pub_hex:
            x25519_pub_hex = to_pubkey  # Fallback: treat pubkey as X25519

        encrypted_text: Optional[str] = None
        try:
            their_x25519 = hex_to_bytes(x25519_pub_hex)
            my_x25519 = hex_to_bytes(self.identity["x25519_secret"])
            encrypted_text = encrypt_for_recipient(
                text.encode("utf-8"), my_x25519, their_x25519
            )
        except Exception:
            encrypted_text = None

        msg: dict = {
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
                "to": to_name,
                "text": text[:50],
                "encrypted": msg["encrypted"],
            })
        return ok

    def poll_dms(self) -> list[dict]:
        """Poll for incoming direct messages, decrypting E2E-encrypted ones.

        Returns:
            List of DM dicts. Encrypted messages include a ``_decrypted``
            boolean and the plaintext ``text`` field on success.
        """
        topic = DM_TOPIC(self.identity["pubkey"])
        messages = self.transport.poll_json(topic)
        dms: list[dict] = []

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

    # ── Tasks ─────────────────────────────────────────────────────────────

    def send_task(
        self, to_pubkey: str, description: str, task_type: str = "general"
    ) -> str:
        """Send a task request to another agent.

        Args:
            to_pubkey: Target agent's Ed25519 public key (hex).
            description: Human-readable task description.
            task_type: Task category tag.

        Returns:
            The generated ``task_id`` string.
        """
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
                "to": to_name,
                "task_id": task_id,
                "description": description,
            })
        return task_id

    def respond_task(
        self, task_id: str, result: str, status: str = "completed"
    ) -> bool:
        """Respond to a task with results.

        Args:
            task_id: The task to respond to.
            result: Result payload.
            status: Task status (e.g. ``completed``, ``failed``).

        Returns:
            ``True`` if the response was published successfully.
        """
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
                "task_id": task_id,
                "status": status,
                "result": result[:100],
            })
        return ok

    def poll_tasks(self) -> list[dict]:
        """Poll for incoming task requests addressed to this agent.

        Returns:
            List of task request dicts.
        """
        topic = DM_TOPIC(self.identity["pubkey"])
        messages = self.transport.poll_json(topic)
        tasks = [m for m in messages if m.get("type") == "task_request"]
        for t in tasks:
            self._log_dashboard("task_recv", {
                "from": t.get("from", "unknown"),
                "task_id": t.get("task_id", ""),
                "description": t.get("description", ""),
            })
        return tasks

    def poll_commands(self) -> list[dict]:
        """Poll for incoming commands from dashboard.

        Returns:
            List of command dicts.
        """
        topic = f"/claku/1/command/{self.identity['pubkey']}/proto"
        messages = self.transport.poll_json(topic)
        commands = [m for m in messages if m.get("type") == "command"]
        
        for cmd in commands:
            self._log_dashboard("command_recv", {
                "from": cmd.get("from", "unknown"),
                "command": cmd.get("command", ""),
                "msg_id": cmd.get("msg_id", ""),
            })
            
            # Execute command
            self._execute_command(cmd)
        
        return commands

    def _execute_command(self, cmd: dict) -> None:
        """Execute a command from the dashboard.

        Args:
            cmd: Command dict with 'command' and 'params' fields.
        """
        command = cmd.get("command")
        params = cmd.get("params", {})
        
        try:
            if command == "announce":
                self.announce()
            elif command == "discover":
                self.discover()
            elif command == "send_channel":
                channel = params.get("channel", "").replace("#", "")
                text = params.get("text", "")
                if channel and text:
                    self.send_channel(channel, text)
            elif command == "join_channel":
                channel = params.get("channel", "").replace("#", "")
                if channel:
                    self.channels.add(channel)
            elif command == "leave_channel":
                channel = params.get("channel", "").replace("#", "")
                if channel and channel in self.channels:
                    self.channels.remove(channel)
            else:
                self._log_dashboard("command_error", {
                    "msg_id": cmd.get("msg_id"),
                    "error": f"Unknown command: {command}"
                })
        except Exception as e:
            self._log_dashboard("command_error", {
                "msg_id": cmd.get("msg_id"),
                "error": str(e)
            })

    # ── Circles ────────────────────────────────────────────────────────────

    def circle_create(self, name: str, description: str = "") -> dict:
        """Create a new Circle (governance structure).

        Args:
            name: Circle name (lowercase, no spaces — e.g. ``privacy-tools``).
            description: Optional human-readable description.

        Returns:
            The circle metadata dict.

        Raises:
            ValueError: If a circle with this name already exists locally.
        """
        circles = _load_circles()
        if name in circles:
            raise ValueError(f"Circle '{name}' already exists")

        circle = {
            "name": name,
            "description": description,
            "created_by": self.identity["name"],
            "created_by_pubkey": self.identity["pubkey"],
            "created_at": int(time.time()),
            "members": [
                {
                    "name": self.identity["name"],
                    "pubkey": self.identity["pubkey"],
                    "joined_at": int(time.time()),
                }
            ],
        }
        circles[name] = circle
        _save_circles(circles)

        # Announce creation on the circle msg topic
        msg = {
            "v": 1,
            "type": "circle_create",
            "circle": name,
            "description": description,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }
        sign_data = f"{msg['msg_id']}:{name}:create".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        msg["signature"] = sign_message(sign_data, ed_priv)
        self.transport.publish_json(CIRCLE_MSG_TOPIC(name), msg)

        self._log_dashboard("circle_create", {
            "circle": name,
            "description": description,
        })
        return circle

    def circle_join(self, name: str) -> bool:
        """Join an existing Circle.

        Args:
            name: Circle name to join.

        Returns:
            ``True`` if successfully joined.
        """
        circles = _load_circles()
        if name not in circles:
            # Create a minimal local entry if we're joining a remote circle
            circles[name] = {
                "name": name,
                "description": "",
                "created_by": "unknown",
                "created_by_pubkey": "",
                "created_at": int(time.time()),
                "members": [],
            }

        # Check if already a member
        members = circles[name]["members"]
        if any(m["pubkey"] == self.identity["pubkey"] for m in members):
            return True  # Already a member

        members.append({
            "name": self.identity["name"],
            "pubkey": self.identity["pubkey"],
            "joined_at": int(time.time()),
        })
        _save_circles(circles)

        # Announce join
        msg = {
            "v": 1,
            "type": "circle_join",
            "circle": name,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }
        sign_data = f"{msg['msg_id']}:{name}:join".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        msg["signature"] = sign_message(sign_data, ed_priv)
        self.transport.publish_json(CIRCLE_MSG_TOPIC(name), msg)

        self._log_dashboard("circle_join", {"circle": name})
        return True

    def circle_leave(self, name: str) -> bool:
        """Leave a Circle.

        Args:
            name: Circle name to leave.

        Returns:
            ``True`` if successfully left (or was not a member).
        """
        circles = _load_circles()
        if name not in circles:
            return True

        members = circles[name]["members"]
        circles[name]["members"] = [
            m for m in members if m["pubkey"] != self.identity["pubkey"]
        ]
        _save_circles(circles)

        # Announce leave
        msg = {
            "v": 1,
            "type": "circle_leave",
            "circle": name,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }
        sign_data = f"{msg['msg_id']}:{name}:leave".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        msg["signature"] = sign_message(sign_data, ed_priv)
        self.transport.publish_json(CIRCLE_MSG_TOPIC(name), msg)

        self._log_dashboard("circle_leave", {"circle": name})
        return True

    def circle_list(self) -> dict[str, dict]:
        """List all circles this agent is a member of.

        Returns:
            Dict mapping circle name to circle metadata.
        """
        circles = _load_circles()
        my_circles: dict[str, dict] = {}
        for name, circle in circles.items():
            if any(m["pubkey"] == self.identity["pubkey"] for m in circle["members"]):
                my_circles[name] = circle
        return my_circles

    def circle_members(self, name: str) -> list[dict]:
        """List members of a Circle.

        Args:
            name: Circle name.

        Returns:
            List of member dicts with name, pubkey, joined_at.
        """
        circles = _load_circles()
        if name not in circles:
            return []
        return circles[name]["members"]

    def circle_propose(
        self,
        circle_name: str,
        title: str,
        description: str,
        vote_deadline: int,
        quorum: int,
        action_type: str = "general",
    ) -> str:
        """Create a proposal within a Circle.

        Args:
            circle_name: Circle to propose in.
            title: Proposal title.
            description: Proposal description.
            vote_deadline: Unix timestamp when voting closes.
            quorum: Minimum number of votes required.
            action_type: Category of action (e.g. ``build``, ``fund``, ``general``).

        Returns:
            The generated proposal_id.

        Raises:
            ValueError: If not a member of the circle.
        """
        circles = _load_circles()
        if circle_name not in circles:
            raise ValueError(f"Circle '{circle_name}' not found")
        members = circles[circle_name]["members"]
        if not any(m["pubkey"] == self.identity["pubkey"] for m in members):
            raise ValueError(f"Not a member of circle '{circle_name}'")

        proposal_id = str(uuid.uuid4())
        proposal = {
            "v": 1,
            "type": "proposal",
            "proposal_id": proposal_id,
            "circle": circle_name,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "title": title,
            "description": description,
            "action_type": action_type,
            "vote_deadline": vote_deadline,
            "quorum": quorum,
            "votes_yes": 0,
            "votes_no": 0,
            "voters": [],
            "status": "open",
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }

        # Sign the proposal
        sign_data = f"{proposal['msg_id']}:{circle_name}:{title}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        proposal["signature"] = sign_message(sign_data, ed_priv)

        # Publish to the proposal topic
        self.transport.publish_json(CIRCLE_PROPOSAL_TOPIC(circle_name), proposal)

        # Store locally
        proposals = _load_proposals()
        proposals[proposal_id] = proposal
        _save_proposals(proposals)

        self._log_dashboard("circle_propose", {
            "circle": circle_name,
            "proposal_id": proposal_id,
            "title": title,
            "quorum": quorum,
            "vote_deadline": vote_deadline,
        })
        return proposal_id

    def circle_vote(
        self, circle_name: str, proposal_id: str, vote: bool
    ) -> bool:
        """Vote on a proposal within a Circle.

        Args:
            circle_name: Circle the proposal belongs to.
            proposal_id: ID of the proposal to vote on.
            vote: ``True`` for yes, ``False`` for no.

        Returns:
            ``True`` if the vote was recorded.

        Raises:
            ValueError: If not a member, proposal not found, already voted,
                or voting has closed.
        """
        circles = _load_circles()
        if circle_name not in circles:
            raise ValueError(f"Circle '{circle_name}' not found")
        members = circles[circle_name]["members"]
        if not any(m["pubkey"] == self.identity["pubkey"] for m in members):
            raise ValueError(f"Not a member of circle '{circle_name}'")

        proposals = _load_proposals()
        if proposal_id not in proposals:
            raise ValueError(f"Proposal '{proposal_id}' not found")

        proposal = proposals[proposal_id]
        if proposal["circle"] != circle_name:
            raise ValueError("Proposal does not belong to this circle")
        if proposal["status"] != "open":
            raise ValueError(f"Proposal is '{proposal['status']}', not open")
        if int(time.time()) > proposal["vote_deadline"]:
            proposal["status"] = "expired"
            _save_proposals(proposals)
            raise ValueError("Voting deadline has passed")
        if self.identity["pubkey"] in proposal["voters"]:
            raise ValueError("Already voted on this proposal")

        # Record the vote
        if vote:
            proposal["votes_yes"] += 1
        else:
            proposal["votes_no"] += 1
        proposal["voters"].append(self.identity["pubkey"])

        # Check if quorum reached and determine outcome
        total_votes = proposal["votes_yes"] + proposal["votes_no"]
        if total_votes >= proposal["quorum"]:
            if proposal["votes_yes"] > proposal["votes_no"]:
                proposal["status"] = "accepted"
            elif total_votes >= len(members):
                # All members voted, majority decides
                proposal["status"] = "rejected" if proposal["votes_no"] >= proposal["votes_yes"] else "accepted"

        _save_proposals(proposals)

        # Publish vote to the vote topic
        vote_msg = {
            "v": 1,
            "type": "vote",
            "proposal_id": proposal_id,
            "circle": circle_name,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "vote": "yes" if vote else "no",
            "msg_id": str(uuid.uuid4()),
            "ts": int(time.time()),
        }
        sign_data = f"{vote_msg['msg_id']}:{proposal_id}:{'yes' if vote else 'no'}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        vote_msg["signature"] = sign_message(sign_data, ed_priv)
        self.transport.publish_json(CIRCLE_VOTE_TOPIC(circle_name), vote_msg)

        self._log_dashboard("circle_vote", {
            "circle": circle_name,
            "proposal_id": proposal_id,
            "vote": "yes" if vote else "no",
            "votes_yes": proposal["votes_yes"],
            "votes_no": proposal["votes_no"],
            "status": proposal["status"],
        })
        return True

    def circle_proposals(self, circle_name: str) -> list[dict]:
        """List all proposals for a Circle.

        Args:
            circle_name: Circle name.

        Returns:
            List of proposal dicts, sorted by creation time (newest first).
        """
        proposals = _load_proposals()
        circle_props = [
            p for p in proposals.values() if p["circle"] == circle_name
        ]
        # Update expired proposals
        now = int(time.time())
        for p in circle_props:
            if p["status"] == "open" and now > p["vote_deadline"]:
                p["status"] = "expired"
                proposals[p["proposal_id"]] = p
        _save_proposals(proposals)

        return sorted(circle_props, key=lambda p: p["ts"], reverse=True)

    def circle_poll_proposals(self, circle_name: str) -> list[dict]:
        """Poll the network for proposals in a Circle.

        Args:
            circle_name: Circle name.

        Returns:
            List of proposal dicts from the network.
        """
        messages = self.transport.poll_json(CIRCLE_PROPOSAL_TOPIC(circle_name))
        proposals = _load_proposals()
        new_proposals: list[dict] = []

        for msg in messages:
            if msg.get("type") != "proposal":
                continue
            pid = msg.get("proposal_id", "")
            if pid and pid not in proposals:
                proposals[pid] = msg
                new_proposals.append(msg)
                self._log_dashboard("circle_proposal_recv", {
                    "circle": circle_name,
                    "proposal_id": pid,
                    "title": msg.get("title", ""),
                    "from": msg.get("from", "unknown"),
                })

        if new_proposals:
            _save_proposals(proposals)
        return new_proposals

    def circle_poll_votes(self, circle_name: str) -> list[dict]:
        """Poll the network for votes in a Circle.

        Args:
            circle_name: Circle name.

        Returns:
            List of vote dicts from the network.
        """
        messages = self.transport.poll_json(CIRCLE_VOTE_TOPIC(circle_name))
        proposals = _load_proposals()
        new_votes: list[dict] = []

        for msg in messages:
            if msg.get("type") != "vote":
                continue
            pid = msg.get("proposal_id", "")
            voter_pubkey = msg.get("from_pubkey", "")
            if pid in proposals and voter_pubkey not in proposals[pid].get("voters", []):
                proposal = proposals[pid]
                if msg.get("vote") == "yes":
                    proposal["votes_yes"] = proposal.get("votes_yes", 0) + 1
                else:
                    proposal["votes_no"] = proposal.get("votes_no", 0) + 1
                proposal.setdefault("voters", []).append(voter_pubkey)
                new_votes.append(msg)
                self._log_dashboard("circle_vote_recv", {
                    "circle": circle_name,
                    "proposal_id": pid,
                    "from": msg.get("from", "unknown"),
                    "vote": msg.get("vote", "?"),
                })

        if new_votes:
            _save_proposals(proposals)
        return new_votes

    # ── Connections ───────────────────────────────────────────────────────

    def send_connection_request(self, to_pubkey: str, reason: str = "") -> bool:
        """Send a connection request to another agent's inbox."""
        msg = {
            "type": "connection_request",
            "from": self.identity["pubkey"],
            "from_pubkey": self.identity["pubkey"],
            "from_name": self.identity["name"],
            "from_capabilities": self.identity["capabilities"],
            "to": to_pubkey,
            "reason": reason,
        }
        sign_msg(msg, self.identity["secret"])
        topic = f"/claku/1/inbox/{to_pubkey[:32]}/proto"
        ok = self.transport.publish_json(topic, msg)
        if ok:
            self._log_dashboard("connection_request_sent", {"to": to_pubkey[:16]})
        return ok

    def accept_connection(self, request_msg: dict) -> bool:
        """Accept a connection request."""
        from_pk = request_msg.get("from_pubkey", request_msg.get("from", ""))
        if not from_pk:
            return False
        msg = {
            "type": "connection_accept",
            "from": self.identity["pubkey"],
            "from_pubkey": self.identity["pubkey"],
            "to": from_pk,
            "request_id": request_msg.get("msg_id", ""),
        }
        sign_msg(msg, self.identity["secret"])
        topic = f"/claku/1/inbox/{from_pk[:32]}/proto"
        ok = self.transport.publish_json(topic, msg)
        if ok:
            self.connections.accept_connection(from_pk, request_msg.get("from_name", ""))
            self._log_dashboard("connection_accepted", {"from": from_pk[:16]})
        return ok

    def refuse_connection(self, request_msg: dict, reason: str = "") -> bool:
        """Refuse a connection request."""
        from_pk = request_msg.get("from_pubkey", request_msg.get("from", ""))
        if not from_pk:
            return False
        msg = {
            "type": "connection_refuse",
            "from": self.identity["pubkey"],
            "from_pubkey": self.identity["pubkey"],
            "to": from_pk,
            "request_id": request_msg.get("msg_id", ""),
            "reason": reason,
        }
        sign_msg(msg, self.identity["secret"])
        topic = f"/claku/1/inbox/{from_pk[:32]}/proto"
        ok = self.transport.publish_json(topic, msg)
        if ok:
            self._log_dashboard("connection_refused", {"from": from_pk[:16]})
        return ok

    def poll_inbox(self) -> list[dict]:
        """Poll this agent's inbox for connection requests and responses."""
        my_pk = self.identity["pubkey"]
        topic = f"/claku/1/inbox/{my_pk[:32]}/proto"
        messages = []

        # Store + relay
        try:
            for msg in self.transport.store_query_json([topic]):
                valid, _ = validate_msg(msg)
                if valid:
                    messages.append(msg)
        except Exception:
            pass
        for msg in self.transport.poll_json(topic):
            valid, _ = validate_msg(msg)
            if valid:
                messages.append(msg)

        # Auto-accept if configured
        results = []
        for msg in messages:
            mtype = msg.get("type", "")
            if mtype == "connection_request":
                from_pk = msg.get("from_pubkey", msg.get("from", ""))
                if self.connections.should_auto_accept(
                    from_pk,
                    msg.get("from_capabilities", []),
                ):
                    self.accept_connection(msg)
                    msg["_auto_accepted"] = True
                else:
                    msg["_pending"] = True
            results.append(msg)

        return results

    # ── Pairing ──────────────────────────────────────────────────────────

    def create_pairing_code(self) -> dict:
        """Generate a pairing code for human-agent pairing.

        Returns:
            Dict with code, agent_pubkey, eph_public, expires.
        """
        offer = self.pairing.create_offer(
            self.identity["pubkey"],
            self.identity["x25519_pubkey"],
        )
        self._log_dashboard("pairing_offer", {"code": offer["code"]})
        return offer

    def complete_pairing(self, code: str, human_x25519_pub_hex: str) -> dict | None:
        """Complete a pairing using the code and human's public key.

        Returns:
            Pairing dict or None if code invalid/expired.
        """
        result = self.pairing.accept_offer(code, human_x25519_pub_hex)
        if result:
            self._log_dashboard("pairing_complete", {
                "human_pubkey": human_x25519_pub_hex[:16],
            })
        return result

    # ── Run Loop ──────────────────────────────────────────────────────────

    def run_once(self) -> dict:
        """Execute a single poll cycle across all message types.

        Checks discovery, DMs, tasks, commands, all joined channels, and all circles.

        Returns:
            Dict with keys ``discovered``, ``dms``, ``tasks``, ``commands``,
            ``channels``, and ``circles``.
        """
        results: dict = {
            "discovered": self.discover(),
            "dms": self.poll_dms(),
            "tasks": self.poll_tasks(),
            "commands": self.poll_commands(),
            "channels": {},
            "circles": {},
        }
        for ch in self.channels:
            msgs = self.poll_channel(ch)
            if msgs:
                results["channels"][ch] = msgs
        # Poll all circles we're a member of
        for name in self.circle_list():
            circle_results: dict = {
                "proposals": self.circle_poll_proposals(name),
                "votes": self.circle_poll_votes(name),
            }
            if circle_results["proposals"] or circle_results["votes"]:
                results["circles"][name] = circle_results
        return results
