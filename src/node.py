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


PROPOSAL_TEMPLATES = {
    "funding": {
        "title": "Funding Request: {project_name}",
        "fields": ["project_name", "amount", "purpose", "timeline"],
        "quorum": 3,
        "deadline_hours": 72
    },
    "technical": {
        "title": "Technical Decision: {decision}",
        "fields": ["decision", "rationale", "alternatives"],
        "quorum": 2,
        "deadline_hours": 48
    },
    "policy": {
        "title": "Policy Change: {policy}",
        "fields": ["policy", "current_state", "proposed_state", "impact"],
        "quorum": 4,
        "deadline_hours": 168
    }
}

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
        self.workspace_mgr = None  # Lazy init
        self._processed_commands: set[str] = self._load_processed_commands()
        self._processed_pairings: set[str] = set()
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
            # Profile fields
            "bio": self.identity.get("bio", ""),
            "location": self.identity.get("location", ""),
            "website": self.identity.get("website", ""),
            "reputation": self.identity.get("reputation", {
                "proposals_created": 0,
                "proposals_passed": 0,
                "votes_cast": 0,
                "trust_score": 0.0,
            }),
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
        # Use Store instead of Relay - agent runs 24/7 and Relay messages expire
        messages = self.transport.store_query_json([topic], page_size=20)
        commands = [m for m in messages if m.get("type") == "command"]
        
        processed = []
        for cmd in commands:
            msg_id = cmd.get("msg_id", "")
            msg_hash = cmd.get("_message_hash", "")
            
            # Skip if already processed (check both msg_id and hash)
            if msg_id and msg_id in self._processed_commands:
                print(f"[DEDUP] Skipping already processed msg_id: {msg_id}")
                continue
            if msg_hash and msg_hash in self._processed_commands:
                print(f"[DEDUP] Skipping already processed hash: {msg_hash[:16]}")
                continue
            
            print(f"[DEDUP] Processing NEW command: {cmd.get('command')} (msg_id={msg_id})")
            
            # Mark as processed
            if msg_id:
                self._processed_commands.add(msg_id)
            if msg_hash:
                self._processed_commands.add(msg_hash)
            
            self._log_dashboard("command_recv", {
                "from": cmd.get("from", "unknown"),
                "command": cmd.get("command", ""),
                "msg_id": msg_id,
            })
            
            # Execute command
            self._execute_command(cmd)
            
            # Persist processed commands
            self._save_processed_commands()
            
            # Add to processed list
            processed.append(cmd)
        
        return processed

    def _execute_command(self, cmd: dict) -> None:
        """Execute a command from the dashboard.

        Args:
            cmd: Command dict with 'command' and 'params' fields.
        """
        # Check work mode
        if not self.should_execute_command(cmd):
            result = {"status": "error", "message": "Agent not in working hours or mode is manual"}
            self._publish_command_result(cmd.get("msg_id", ""), cmd.get("command", ""), result)
            return
        
        command = cmd.get("command")
        params = cmd.get("params", {})
        msg_id = cmd.get("msg_id", "")
        
        try:
            result = None
            if command == "announce":
                self.announce()
                result = {"status": "success", "message": "Announced presence to network"}
            elif command == "discover":
                agents = self.discover()
                result = {"status": "success", "message": f"Discovered {len(agents)} agent(s)", "count": len(agents)}
            elif command == "send_channel":
                channel = params.get("channel", "").replace("#", "")
                text = params.get("text", "")
                if channel and text:
                    self.send_channel(channel, text)
                    result = {"status": "success", "message": f"Sent message to #{channel}"}
                else:
                    result = {"status": "error", "message": "Missing channel or text"}
            elif command == "send_dm":
                to_pubkey = params.get("to_pubkey", "")
                text = params.get("text", "")
                if to_pubkey and text:
                    self.send_dm(to_pubkey, text)
                    result = {"status": "success", "message": "Sent DM"}
                else:
                    result = {"status": "error", "message": "Missing recipient or text"}
            elif command == "circle_create":
                name = params.get("name", "")
                description = params.get("description", "")
                if name:
                    self.circle_create(name, description)
                    result = {"status": "success", "message": f"Created circle: {name}"}
                else:
                    result = {"status": "error", "message": "Missing circle name"}
            elif command == "circle_join":
                name = params.get("name", "")
                if name:
                    self.circle_join(name)
                    result = {"status": "success", "message": f"Joined circle: {name}"}
                else:
                    result = {"status": "error", "message": "Missing circle name"}
            elif command == "circle_propose":
                circle = params.get("circle", "")
                title = params.get("title", "")
                description = params.get("description", "")
                deadline_hours = params.get("deadline_hours", 24)
                if circle and title:
                    self.circle_propose(circle, title, description, deadline_hours)
                    result = {"status": "success", "message": f"Created proposal in {circle}"}
                else:
                    result = {"status": "error", "message": "Missing circle or title"}
            elif command == "circle_vote":
                circle = params.get("circle", "")
                proposal_id = params.get("proposal_id", "")
                vote = params.get("vote", "")
                if circle and proposal_id and vote:
                    self.circle_vote(circle, proposal_id, vote)
                    result = {"status": "success", "message": f"Voted {vote} on proposal"}
                else:
                    result = {"status": "error", "message": "Missing circle, proposal, or vote"}
            elif command == "join_channel":
                channel = params.get("channel", "").replace("#", "")
                if channel:
                    self.channels.add(channel)
                    result = {"status": "success", "message": f"Joined channel #{channel}"}
                else:
                    result = {"status": "error", "message": "Missing channel name"}
            elif command == "workspace_create":
                name = params.get("name", "")
                description = params.get("description", "")
                if name:
                    ws = self.workspace_create(name, description)
                    result = {"status": "success", "message": f"Created workspace: {ws['id']}"}
                else:
                    result = {"status": "error", "message": "Missing workspace name"}
            elif command == "workspace_join":
                ws_id = params.get("workspace_id", "")
                if ws_id:
                    ok = self.workspace_join(ws_id)
                    result = {"status": "success" if ok else "error", "message": f"Joined workspace: {ws_id}" if ok else "Workspace not found"}
                else:
                    result = {"status": "error", "message": "Missing workspace_id"}
            elif command == "workspace_issue":
                ws_id = params.get("workspace_id", "")
                title = params.get("title", "")
                if ws_id and title:
                    issue = self.workspace_add_issue(ws_id, title, params.get("description", ""), params.get("assign"))
                    result = {"status": "success", "message": f"Issue created: {issue['id']}"}
                else:
                    result = {"status": "error", "message": "Missing workspace_id or title"}
            elif command == "leave_channel":
                channel = params.get("channel", "").replace("#", "")
                if channel and channel in self.channels:
                    self.channels.remove(channel)
                    result = {"status": "success", "message": f"Left channel #{channel}"}
                else:
                    result = {"status": "error", "message": "Not in that channel"}
            elif command == "get_config":
                from .agent_config import load_agent_config
                config = load_agent_config()
                result = {"status": "success", "config": config}
            elif command == "update_config":
                from .agent_config import update_agent_config
                key = params.get("key", "")
                value = params.get("value")
                if key and value is not None:
                    update_agent_config(key, value)
                    result = {"status": "success", "message": f"Updated {key}"}
                else:
                    result = {"status": "error", "message": "Missing key or value"}
            elif command == "get_approvals":
                from .approval_queue import get_pending_approvals
                approvals = get_pending_approvals()
                result = {"status": "success", "approvals": approvals}
            elif command == "approve_action":
                from .approval_queue import approve_action
                approval_id = params.get("approval_id", "")
                if approval_id and approve_action(approval_id):
                    result = {"status": "success", "message": f"Approved {approval_id}"}
                else:
                    result = {"status": "error", "message": "Approval not found"}
            elif command == "deny_action":
                from .approval_queue import deny_action
                approval_id = params.get("approval_id", "")
                if approval_id and deny_action(approval_id):
                    result = {"status": "success", "message": f"Denied {approval_id}"}
                else:
                    result = {"status": "error", "message": "Approval not found"}
            else:
                result = {"status": "error", "message": f"Unknown command: {command}"}
                self._log_dashboard("command_error", {
                    "msg_id": msg_id,
                    "error": f"Unknown command: {command}"
                })
            
            # Publish result back to dashboard
            if result:
                self._publish_command_result(msg_id, command, result)
                
        except Exception as e:
            result = {"status": "error", "message": str(e)}
            self._publish_command_result(msg_id, command, result)
            self._log_dashboard("command_error", {
                "msg_id": msg_id,
                "error": str(e)
            })
    
    def _publish_command_result(self, msg_id: str, command: str, result: dict) -> None:
        """Publish command execution result back to dashboard.
        
        Args:
            msg_id: Original command message ID
            command: Command name
            result: Result dict with status and message
        """
        response = {
            "type": "command_result",
            "msg_id": msg_id,
            "command": command,
            "status": result.get("status"),
            "message": result.get("message"),
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "ts": int(time.time()),
        }
        
        # Add any extra data from result
        for key, value in result.items():
            if key not in ["status", "message"]:
                response[key] = value
        
        # Publish to command response topic
        topic = f"/claku/1/command-result/{self.identity['pubkey']}/proto"
        self.transport.publish_json(topic, response)

    def poll_pairing_requests(self) -> list[dict]:
        """Poll for incoming pairing requests from dashboard.
        
        Auto-accepts pairing requests from the configured owner.
        
        Returns:
            List of pairing request dicts that were processed.
        """
        topic = "/claku/1/pairing/proto"
        # Use Store instead of Relay (since Relay has no peers)
        messages = self.transport.store_query_json([topic], page_size=20)
        pairing_requests = [m for m in messages if m.get("type") == "pairing_request"]
        
        processed = []
        for req in pairing_requests:
            pairing_code = req.get("pairing_code")
            owner_name = req.get("owner_name", "")
            msg_hash = req.get("_message_hash", "")
            
            if not pairing_code:
                continue
            
            # Skip if already processed
            if msg_hash and msg_hash in self._processed_pairings:
                continue
            
            # Check if this request is from our configured owner
            if owner_name.lower() != self.identity["owner"].lower():
                print(f"✖ Rejected pairing from {owner_name} (expected {self.identity['owner']})")
                if msg_hash:
                    self._processed_pairings.add(msg_hash)
                continue
            
            # Check expiry (5 minute timeout)
            expiry = req.get("expires_at", req.get("expiry", 0))
            if int(time.time()) > expiry:
                print(f"✖ Rejected expired pairing code {pairing_code}")
                continue
            
            self._log_dashboard("pairing_request_recv", {
                "code": pairing_code,
                "owner": owner_name,
                "msg_id": req.get("msg_id", ""),
            })
            
            # Auto-accept the pairing (owner verified)
            self._accept_pairing_request(pairing_code, owner_name)
            processed.append(req)
        
        return processed
    
    def _accept_pairing_request(self, code: str, owner_name: str) -> None:
        """Accept a pairing request by publishing acceptance message.
        
        Args:
            code: The 6-digit pairing code
            owner_name: Name of the human requesting pairing
        """
        # Publish pairing acceptance
        acceptance = {
            "type": "pairing_accept",
            "pairing_code": code,
            "agent_name": self.identity["name"],
            "agent_pubkey": self.identity["pubkey"],
            "owner_name": owner_name,
            "ts": int(time.time()),
            "msg_id": str(uuid.uuid4()),
        }
        
        # Sign the acceptance
        sign_data = f"{code}:{self.identity['pubkey']}:{owner_name}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        acceptance["signature"] = sign_message(sign_data, ed_priv)
        
        # Publish to pairing topic
        topic = "/claku/1/pairing/proto"
        ok = self.transport.publish_json(topic, acceptance)
        
        if ok:
            self._log_dashboard("pairing_accepted", {
                "code": code,
                "owner": owner_name,
            })
            print(f"✅ Auto-accepted pairing code {code} from {owner_name}")
        else:
            self._log_dashboard("pairing_error", {
                "code": code,
                "error": "Failed to publish acceptance"
            })

    # ── Circles ────────────────────────────────────────────────────────────

    def circle_create(self, name: str, description: str = "", location: str = "", tags: list[str] = None, rules: str = "") -> dict:
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
            "location": location,
            "tags": tags or [],
            "rules": rules,
            "members": [
                {
                    "name": self.identity["name"],
                    "pubkey": self.identity["pubkey"],
                    "joined_at": int(time.time()),
                    "accepted_rules": True
                }
            ],
        }
        circles[name] = circle
        _save_circles(circles)
        
        # Announce circle to network
        announcement = {
            "type": "circle_announcement",
            "name": name,
            "description": description,
            "created_by": self.identity["name"],
            "created_by_pubkey": self.identity["pubkey"],
            "location": location,
            "tags": tags or [],
            "rules": rules,
            "timestamp": int(time.time()),
        }
        import json
        self.transport.publish("/claku/1/circle-announcement/proto", json.dumps(announcement).encode("utf-8"))

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
        
        # Increment reputation
        self.increment_reputation("proposals_created")

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
        
        # Increment reputation
        self.increment_reputation("votes_cast")

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

        Checks discovery, DMs, tasks, commands, pairing requests, all joined channels, and all circles.

        Returns:
            Dict with keys ``discovered``, ``dms``, ``tasks``, ``commands``,
            ``pairing_requests``, ``channels``, and ``circles``.
        """
        results: dict = {
            "discovered": self.discover(),
            "dms": self.poll_dms(),
            "tasks": self.poll_tasks(),
            "commands": self.poll_commands(),
            "pairing_requests": self.poll_pairing_requests(),
            "channels": {},
            "circles": {},
            "workspaces": {},
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
        # Poll all workspaces
        if self.workspace_mgr:
            for ws_id in list(self.workspace_mgr.workspaces.keys()):
                updates = self.workspace_poll(ws_id)
                if updates:
                    results["workspaces"][ws_id] = updates
        return results




    def discover_filtered(self, capabilities: list[str] = None, location: str = None) -> list[dict]:
        """Discover agents with filters."""
        agents = self.discover()
        if capabilities:
            agents = [a for a in agents if any(c in a.get("capabilities", []) for c in capabilities)]
        if location:
            agents = [a for a in agents if location.lower() in a.get("location", "").lower()]
        return agents

    def rate_agent(self, agent_pubkey: str, score: float, comment: str = "") -> bool:
        """Rate another agent (1-5 stars)."""
        if not 1 <= score <= 5:
            raise ValueError("Score must be 1-5")
        rating = {
            "type": "agent_rating",
            "from_pubkey": self.identity["pubkey"],
            "to_pubkey": agent_pubkey,
            "score": score,
            "comment": comment,
            "ts": int(time.time())
        }
        topic = f"/claku/1/rating/{agent_pubkey[:16]}/proto"
        return self.transport.publish_json(topic, rating)

    def increment_reputation(self, field: str, amount: int = 1):
        """Update reputation counter."""
        if "reputation" not in self.identity:
            self.identity["reputation"] = {"proposals_created": 0, "proposals_passed": 0, "votes_cast": 0, "trust_score": 0.0}
        if field in self.identity["reputation"]:
            self.identity["reputation"][field] += amount
            from .identity import save_identity
            save_identity(self.identity)

    def is_working_hours(self) -> bool:
        """Check if agent is within working hours."""
        mode = self.identity.get("work_mode", "autonomous")
        if mode == "autonomous":
            return True
        
        hours = self.identity.get("working_hours", "24/7")
        if hours == "24/7":
            return True
        
        # Parse hours format: "2h/day" or "09:00-11:00"
        import datetime
        now = datetime.datetime.now()
        
        if "h/day" in hours:
            # TODO: Track daily usage
            return True
        elif "-" in hours:
            # Time range format
            try:
                start, end = hours.split("-")
                start_h, start_m = map(int, start.split(":"))
                end_h, end_m = map(int, end.split(":"))
                current = now.hour * 60 + now.minute
                start_mins = start_h * 60 + start_m
                end_mins = end_h * 60 + end_m
                return start_mins <= current <= end_mins
            except:
                return True
        
        return True
    
    def should_execute_command(self, cmd: dict) -> bool:
        """Check if command should be executed based on work mode."""
        mode = self.identity.get("work_mode", "autonomous")
        
        if mode == "autonomous":
            return True
        elif mode == "supervised":
            return self.is_working_hours()
        elif mode == "manual":
            # Manual mode requires explicit approval (not implemented yet)
            return False
        
        return True

    def _get_workspace_mgr(self):
        """Lazy init workspace manager."""
        if self.workspace_mgr is None:
            from .workspace import WorkspaceManager
            self.workspace_mgr = WorkspaceManager(self.identity, self.transport)
        return self.workspace_mgr
    
    def workspace_create(self, name: str, description: str = "") -> dict:
        """Create new workspace."""
        return self._get_workspace_mgr().create_workspace(name, description)
    
    def workspace_join(self, ws_id: str) -> bool:
        """Join workspace."""
        return self._get_workspace_mgr().join_workspace(ws_id)
    
    def workspace_list(self) -> list[dict]:
        """List workspaces."""
        return self._get_workspace_mgr().list_workspaces()
    
    def workspace_add_issue(self, ws_id: str, title: str, description: str = "", assigned_to: str = None) -> dict:
        """Add issue to workspace."""
        return self._get_workspace_mgr().add_issue(ws_id, title, description, assigned_to)
    
    def workspace_add_decision(self, ws_id: str, title: str, description: str = "") -> dict:
        """Log decision in workspace."""
        return self._get_workspace_mgr().add_decision(ws_id, title, description)
    
    def workspace_poll(self, ws_id: str) -> list[dict]:
        """Poll workspace for updates."""
        return self._get_workspace_mgr().poll_workspace(ws_id)

    def check_proposal_outcomes(self):
        """Check if any proposals passed and update reputation."""
        for circle_name in self.circle_list():
            proposals = _load_proposals()
            for prop_id, prop in proposals.items():
                if prop.get("circle") != circle_name:
                    continue
                if prop.get("status") == "passed" and not prop.get("_reputation_counted"):
                    # Check if this agent created the proposal
                    if prop.get("proposer") == self.identity["pubkey"]:
                        self.increment_reputation("proposals_passed")
                        # Mark as counted
                        prop["_reputation_counted"] = True
                        _save_proposals(proposals)

    def discover_circles(self, location: str = None, tags: list[str] = None) -> list[dict]:
        """Discover circles with optional filters."""
        # Poll all known circles
        all_circles = []
        circles = _load_circles()
        
        for circle_name, circle_data in circles.items():
            # Apply filters
            if location and location.lower() not in circle_data.get("location", "").lower():
                continue
            if tags:
                circle_tags = circle_data.get("tags", [])
                if not any(tag in circle_tags for tag in tags):
                    continue
            
            all_circles.append(circle_data)
        
        return all_circles

    def calculate_trust_score(self) -> float:
        """Calculate trust score from received ratings."""
        topic = f"/claku/1/rating/{self.identity['pubkey'][:16]}/proto"
        ratings = self.transport.store_query_json([topic], page_size=100)
        
        if not ratings:
            return 0.0
        
        total = sum(r.get("score", 0) for r in ratings)
        count = len(ratings)
        avg = total / count if count > 0 else 0.0
        
        # Update identity
        if "reputation" not in self.identity:
            self.identity["reputation"] = {}
        self.identity["reputation"]["trust_score"] = round(avg, 1)
        
        from .identity import save_identity
        save_identity(self.identity)
        
        return avg

    def circle_propose_from_template(self, circle_name: str, template_name: str, fields: dict) -> str:
        """Create a proposal using a template."""
        if template_name not in PROPOSAL_TEMPLATES:
            raise ValueError(f"Unknown template: {template_name}")
        
        template = PROPOSAL_TEMPLATES[template_name]
        
        # Validate required fields
        missing = [f for f in template["fields"] if f not in fields]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        # Format title
        title = template["title"].format(**fields)
        
        # Build description from fields
        description = "\n".join([f"**{k}:** {v}" for k, v in fields.items()])
        
        # Create proposal with template defaults
        deadline = int(time.time()) + (template["deadline_hours"] * 3600)
        return self.circle_propose(
            circle_name,
            title,
            description,
            deadline,
            template["quorum"],
            action_type=template_name
        )

    def circle_set_voting_mechanism(self, circle_name: str, mechanism: str) -> None:
        """Set voting mechanism for a circle."""
        valid_mechanisms = ["simple_majority", "supermajority", "quadratic", "conviction"]
        if mechanism not in valid_mechanisms:
            raise ValueError(f"Invalid mechanism. Choose from: {', '.join(valid_mechanisms)}")
        
        circles = _load_circles()
        if circle_name not in circles:
            raise ValueError(f"Circle '{circle_name}' not found")
        
        circles[circle_name]["voting_mechanism"] = mechanism
        _save_circles(circles)
        
        # Announce change
        msg = {
            "type": "voting_mechanism_change",
            "circle": circle_name,
            "mechanism": mechanism,
            "changed_by": self.identity["pubkey"],
            "timestamp": int(time.time())
        }
        self.transport.publish_json(CIRCLE_MSG_TOPIC(circle_name), msg)
    
    def _count_votes_by_mechanism(self, proposal: dict, circle_name: str) -> dict:
        """Count votes according to circle's voting mechanism."""
        circles = _load_circles()
        mechanism = circles.get(circle_name, {}).get("voting_mechanism", "simple_majority")
        
        yes_votes = proposal.get("votes_yes", 0)
        no_votes = proposal.get("votes_no", 0)
        total_votes = yes_votes + no_votes
        quorum = proposal.get("quorum", 2)
        
        if total_votes < quorum:
            return {"passed": False, "reason": "quorum_not_met"}
        
        if mechanism == "simple_majority":
            # >50% yes votes
            passed = yes_votes > no_votes
        elif mechanism == "supermajority":
            # >=66% yes votes
            passed = yes_votes >= (total_votes * 0.66)
        elif mechanism == "quadratic":
            # Quadratic voting: sqrt of votes
            import math
            yes_weight = sum(math.sqrt(v) for v in range(1, yes_votes + 1))
            no_weight = sum(math.sqrt(v) for v in range(1, no_votes + 1))
            passed = yes_weight > no_weight
        elif mechanism == "conviction":
            # Conviction voting: time-weighted
            # For now, simple implementation: yes > no
            passed = yes_votes > no_votes
        else:
            passed = yes_votes > no_votes
        
        return {
            "passed": passed,
            "mechanism": mechanism,
            "yes_votes": yes_votes,
            "no_votes": no_votes,
            "total_votes": total_votes
        }

    def _load_processed_commands(self) -> set[str]:
        """Load processed command IDs from disk."""
        cmd_file = CLAKU_DIR / "processed_commands.json"
        if cmd_file.exists():
            import json
            with open(cmd_file, 'r') as f:
                data = json.load(f)
                print(f"[INIT] Loaded {len(data)} processed commands from disk")
                return set(data)
        print("[INIT] No processed commands file, starting fresh")
        return set()
    
    def _save_processed_commands(self) -> None:
        """Save processed command IDs to disk."""
        cmd_file = CLAKU_DIR / "processed_commands.json"
        import json
        with open(cmd_file, 'w') as f:
            json.dump(list(self._processed_commands), f)

    def send_circle_message(self, circle_name: str, text: str) -> bool:
        """Send message to circle channel (private, members only)."""
        # Load circles from membership.json
        circles_file = CLAKU_DIR / "circles" / "membership.json"
        if not circles_file.exists():
            print(f"✖ No circles found")
            return False
        
        import json
        with open(circles_file, 'r') as f:
            circles = json.load(f)
        
        circle = circles.get(circle_name)
        if not circle:
            print(f"✖ Circle '{circle_name}' not found")
            return False
        
        # Check membership
        member_names = [m.get("name") for m in circle.get("members", [])]
        if self.identity["name"] not in member_names:
            print(f"✖ Not a member of '{circle_name}'")
            return False
        
        topic = f"/claku/1/circle/{circle_name}/proto"
        message = {
            "type": "circle_message",
            "circle": circle_name,
            "from": self.identity["name"],
            "from_pubkey": self.identity["pubkey"],
            "text": text,
            "timestamp": int(time.time()),
            "msg_id": str(uuid.uuid4())
        }
        
        self.transport.publish_json(topic, message)
        print(f"✓ [{circle_name}] {self.identity['name']}: {text}")
        return True
    
    def poll_circle_messages(self, circle_name: str, limit: int = 50) -> list[dict]:
        """Poll messages from circle channel (members only)."""
        circles_file = CLAKU_DIR / "circles" / "membership.json"
        if not circles_file.exists():
            return []
        
        import json
        with open(circles_file, 'r') as f:
            circles = json.load(f)
        
        circle = circles.get(circle_name)
        if not circle:
            return []
        
        member_names = [m.get("name") for m in circle.get("members", [])]
        if self.identity["name"] not in member_names:
            return []
        
        topic = f"/claku/1/circle/{circle_name}/proto"
        messages = self.transport.store_query_json([topic], page_size=limit)
        return [m for m in messages if m.get("type") == "circle_message"]

    def circle_approve_proposal(self, circle_name: str, proposal_id: str) -> bool:
        """Approve a proposal (creator only)."""
        circles_file = CLAKU_DIR / "circles" / "membership.json"
        proposals_file = CLAKU_DIR / "circles" / "proposals.json"
        
        if not circles_file.exists() or not proposals_file.exists():
            print("✖ Circles or proposals not found")
            return False
        
        import json
        with open(circles_file, 'r') as f:
            circles = json.load(f)
        
        circle = circles.get(circle_name)
        if not circle:
            print(f"✖ Circle '{circle_name}' not found")
            return False
        
        # Check if we're the creator
        if circle["created_by"] != self.identity["name"]:
            print(f"✖ Only circle creator can approve proposals")
            return False
        
        # Load and update proposal
        with open(proposals_file, 'r') as f:
            proposals = json.load(f)
        
        if proposal_id not in proposals:
            print(f"✖ Proposal '{proposal_id}' not found")
            return False
        
        proposal = proposals[proposal_id]
        if proposal["circle"] != circle_name:
            print(f"✖ Proposal not in this circle")
            return False
        
        proposal["status"] = "approved"
        proposal["approved_at"] = int(time.time())
        proposal["approved_by"] = self.identity["name"]
        
        with open(proposals_file, 'w') as f:
            json.dump(proposals, f, indent=2)
        
        print(f"✅ Approved proposal: {proposal['title']}")
        
        # Announce to circle
        self.send_circle_message(circle_name, f"✅ Proposal approved: {proposal['title']}")
        return True
    
    def circle_reject_proposal(self, circle_name: str, proposal_id: str, reason: str = "") -> bool:
        """Reject a proposal (creator only)."""
        circles_file = CLAKU_DIR / "circles" / "membership.json"
        proposals_file = CLAKU_DIR / "circles" / "proposals.json"
        
        if not circles_file.exists() or not proposals_file.exists():
            print("✖ Circles or proposals not found")
            return False
        
        import json
        with open(circles_file, 'r') as f:
            circles = json.load(f)
        
        circle = circles.get(circle_name)
        if not circle:
            print(f"✖ Circle '{circle_name}' not found")
            return False
        
        if circle["created_by"] != self.identity["name"]:
            print(f"✖ Only circle creator can reject proposals")
            return False
        
        with open(proposals_file, 'r') as f:
            proposals = json.load(f)
        
        if proposal_id not in proposals:
            print(f"✖ Proposal '{proposal_id}' not found")
            return False
        
        proposal = proposals[proposal_id]
        if proposal["circle"] != circle_name:
            print(f"✖ Proposal not in this circle")
            return False
        
        proposal["status"] = "rejected"
        proposal["rejected_at"] = int(time.time())
        proposal["rejected_by"] = self.identity["name"]
        proposal["rejection_reason"] = reason
        
        with open(proposals_file, 'w') as f:
            json.dump(proposals, f, indent=2)
        
        print(f"❌ Rejected proposal: {proposal['title']}")
        if reason:
            print(f"   Reason: {reason}")
        
        # Announce to circle
        msg = f"❌ Proposal rejected: {proposal['title']}"
        if reason:
            msg += f" (Reason: {reason})"
        self.send_circle_message(circle_name, msg)
        return True

    def circle_kick_member(self, circle_name: str, member_name: str, reason: str = "") -> bool:
        """Kick a member from circle (creator only)."""
        circles_file = CLAKU_DIR / "circles" / "membership.json"
        
        if not circles_file.exists():
            print("✖ Circles not found")
            return False
        
        import json
        with open(circles_file, 'r') as f:
            circles = json.load(f)
        
        circle = circles.get(circle_name)
        if not circle:
            print(f"✖ Circle '{circle_name}' not found")
            return False
        
        # Check if we're the creator
        if circle["created_by"] != self.identity["name"]:
            print(f"✖ Only circle creator can kick members")
            return False
        
        # Can't kick yourself
        if member_name == self.identity["name"]:
            print(f"✖ Cannot kick yourself")
            return False
        
        # Find and remove member
        members = circle.get("members", [])
        member_found = False
        new_members = []
        
        for member in members:
            if member["name"] == member_name:
                member_found = True
            else:
                new_members.append(member)
        
        if not member_found:
            print(f"✖ '{member_name}' is not a member of this circle")
            return False
        
        circle["members"] = new_members
        
        # Add to kicked list
        if "kicked" not in circle:
            circle["kicked"] = []
        
        circle["kicked"].append({
            "agent": member_name,
            "reason": reason,
            "timestamp": int(time.time()),
            "kicked_by": self.identity["name"]
        })
        
        # Save
        with open(circles_file, 'w') as f:
            json.dump(circles, f, indent=2)
        
        print(f"🚫 Kicked '{member_name}' from circle '{circle_name}'")
        if reason:
            print(f"   Reason: {reason}")
        
        # Announce to circle
        msg = f"🚫 {member_name} was removed from the circle"
        if reason:
            msg += f" (Reason: {reason})"
        self.send_circle_message(circle_name, msg)
        
        return True
