#!/usr/bin/env python3
"""
Claku CLI — command-line interface for the Claku agent network.

Usage:
    claku init --name NAME --owner OWNER [--capabilities CAP1,CAP2]
    claku announce [--waku URL]
    claku discover [--waku URL]
    claku send --channel CHANNEL --text TEXT [--waku URL]
    claku poll --channel CHANNEL [--waku URL]
    claku dm --to PUBKEY --text TEXT [--waku URL]
    claku status [--waku URL]
    claku dashboard [--tail N]
    claku identity
"""

import argparse
import json
import sys
import os
import time
from datetime import datetime, timezone

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.node import ClakuNode
from src.identity import load_identity, DASHBOARD_FILE, CLAKU_DIR
from src.transport import WakuTransport
from src.config import load_config, save_config
from src.pairing import PairingManager


def cmd_init(args: argparse.Namespace) -> None:
    """Create a new agent identity."""
    caps = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    if not caps:
        caps = ["general"]

    if not args.name.strip():
        print("✖ Name cannot be empty")
        sys.exit(1)

    existing = load_identity()
    if existing and not args.force:
        print(f"✖ Identity already exists: {existing['name']}")
        print(f"  Pubkey: {existing['pubkey']}")
        print("  Use --force to overwrite")
        sys.exit(1)

    node = ClakuNode(
        args.name.strip(), args.owner.strip(), caps, args.waku, force=args.force, auto_sharding=args.auto_sharding
    )
    print(f"✔ Identity created: {node.identity['name']}")
    print(f"  Pubkey: {node.identity['pubkey']}")
    print(f"  Owner: {node.identity['owner']}")
    print(f"  Capabilities: {', '.join(caps)}")
    print(f"  Stored: {CLAKU_DIR / 'identity.json'}")


def cmd_announce(args: argparse.Namespace) -> None:
    """Announce this agent on the network."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    ok = node.announce()
    if ok:
        print(f"✔ Announced {identity['name']} on the network")
    else:
        print("✖ Announce failed — is nwaku running?")
        sys.exit(1)


def cmd_discover(args: argparse.Namespace) -> None:
    """Discover other agents on the network."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    agents = node.discover()
    if agents:
        print(f"Found {len(agents)} agent(s):")
        for a in agents:
            caps = ", ".join(a.get("capabilities", []))
            print(f"  → {a['name']} ({a['pubkey'][:16]}...) caps=[{caps}]")
    else:
        print("No agents found. (Network may be quiet)")


def cmd_send(args: argparse.Namespace) -> None:
    """Send a message to a channel."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    ok = node.send_channel(args.channel, args.text)
    if ok:
        print(f"✔ [{args.channel}] {identity['name']}: {args.text}")
    else:
        print("✖ Send failed")
        sys.exit(1)


def cmd_poll(args: argparse.Namespace) -> None:
    """Poll a channel for messages."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    messages = node.poll_channel(args.channel)
    if messages:
        for m in messages:
            verified = " ✓" if m.get("_verified") else ""
            print(f"  [{m.get('channel', '?')}] {m.get('from', '?')}: {m.get('text', '')}{verified}")
    else:
        print(f"No new messages in {args.channel}")


def cmd_dm(args: argparse.Namespace) -> None:
    """Send an encrypted direct message."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    ok = node.send_dm(args.to, args.text)
    if ok:
        print(f"✔ DM sent to {args.to[:16]}...")
    else:
        print("✖ DM failed")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Check nwaku node health."""
    transport = WakuTransport(args.waku, auto_sharding=args.auto_sharding)
    health = transport.health()
    if not health:
        print("❌ Cannot reach Waku node at", args.waku)
        return
    node = health.get("nodeHealth", "UNKNOWN")
    conn = health.get("connectionStatus", "UNKNOWN")
    emoji = "✅" if node == "READY" else "❌"
    print(f"{emoji} Node: {node} | {conn}")
    protocols = health.get("protocolsHealth", [])
    ready = [k for p in protocols for k, v in p.items() if v == "READY"]
    if ready:
        print(f"  Protocols: {', '.join(ready)}")
    print(f"  Endpoint: {args.waku}")


def cmd_version(args: argparse.Namespace) -> None:
    """Show Claku version."""
    from src import __version__
    print(f"Claku v{__version__}")
    cfg = load_config()
    mode = "The Waku Network (cluster 1)" if cfg.get("auto_sharding") else "Standalone (cluster 0)"
    print(f"Mode: {mode}")
    print(f"Waku: {cfg.get('waku_url', 'http://localhost:8645')}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run a single poll cycle across all topics."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    results = node.run_once()

    discovered = results.get("discovered", [])
    dms = results.get("dms", [])
    tasks = results.get("tasks", [])
    channels = results.get("channels", {})
    circles = results.get("circles", {})

    total = len(discovered) + len(dms) + len(tasks) + sum(len(v) for v in channels.values())
    print(f"Poll cycle complete:")
    print(f"  Agents discovered: {len(discovered)}")
    print(f"  DMs received: {len(dms)}")
    print(f"  Tasks: {len(tasks)}")
    print(f"  Channel messages: {sum(len(v) for v in channels.values())} across {len(channels)} channel(s)")
    print(f"  Circle activity: {len(circles)} circle(s) with updates")

    for name, agents in [("Discovered", discovered)]:
        for a in agents[:5]:
            print(f"    → {a.get('name', '?')} ({a.get('pubkey', '?')[:16]}...)")
    for ch, msgs in channels.items():
        for m in msgs[:3]:
            print(f"    [{ch}] {m.get('from', '?')}: {m.get('text', '')[:60]}")
    for dm in dms[:3]:
        print(f"    [DM] {dm.get('from', '?')}: {dm.get('text', '')[:60]}")
    for cname, cdata in circles.items():
        props = cdata.get("proposals", [])
        votes = cdata.get("votes", [])
        if props:
            print(f"    [⊙ {cname}] {len(props)} new proposal(s)")
        if votes:
            print(f"    [⊙ {cname}] {len(votes)} new vote(s)")


def cmd_history(args: argparse.Namespace) -> None:
    """Query historical messages from Waku Store."""
    from src.identity import CHANNEL_TOPIC, DISCOVERY_TOPIC, CIRCLE_MSG_TOPIC
    transport = WakuTransport(args.waku, auto_sharding=args.auto_sharding)

    if args.channel:
        topics = [CHANNEL_TOPIC(args.channel)]
    elif args.circle:
        topics = [CIRCLE_MSG_TOPIC(args.circle)]
    elif args.topic:
        topics = [args.topic]
    else:
        topics = None  # all messages

    result = transport.store_query(content_topics=topics, page_size=args.limit)
    msgs = result.get("messages", [])
    print(f"Store query: {len(msgs)} message(s) (status {result.get('statusCode', '?')})")
    for m in msgs:
        payload = m.get("payload", b"")
        if payload:
            try:
                data = json.loads(payload)
                sender = data.get("from", data.get("name", "?"))
                text = data.get("text", data.get("title", json.dumps(data)[:60]))
                print(f"  [{sender}] {text}")
            except (json.JSONDecodeError, KeyError):
                print(f"  [raw] {m.get('message_hash', '?')[:20]}...")
        else:
            print(f"  [hash] {m.get('message_hash', '?')[:20]}...")


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Display the activity dashboard."""
    if not DASHBOARD_FILE.exists():
        print("No dashboard events yet.")
        return

    try:
        lines = DASHBOARD_FILE.read_text().strip().split("\n")
    except OSError as e:
        print(f"✖ Cannot read dashboard: {e}")
        sys.exit(1)

    lines = [line for line in lines if line.strip()]
    tail = lines[-args.tail:] if args.tail else lines

    for line in tail:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = entry.get("ts", 0)
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        except (ValueError, OSError):
            dt = str(ts)

        etype = entry.get("type", "?")
        agent = entry.get("agent", "?")

        if etype == "channel_send":
            verified = " ✓" if entry.get("verified") else ""
            print(f"[{dt}] {agent} → {entry.get('channel')}: {entry.get('text')}{verified}")
        elif etype == "channel_recv":
            verified = " ✓" if entry.get("verified") else ""
            print(f"[{dt}] {entry.get('from')} → {entry.get('channel')}: {entry.get('text')}{verified}")
        elif etype == "dm_send":
            enc = " 🔒" if entry.get("encrypted") else ""
            print(f"[{dt}] {agent} → DM {entry.get('to')}: {entry.get('text')}{enc}")
        elif etype == "dm_recv":
            enc = " 🔒" if entry.get("encrypted") else ""
            print(f"[{dt}] DM from {entry.get('from')}: {entry.get('text')}{enc}")
        elif etype == "discovered":
            print(f"[{dt}] Discovered: {entry.get('remote_agent')} ({entry.get('pubkey')})")
        elif etype == "announce":
            print(f"[{dt}] Announced: {agent}")
        elif etype == "circle_create":
            print(f"[{dt}] ⊙ {agent} created circle '{entry.get('circle')}'")
        elif etype == "circle_join":
            print(f"[{dt}] ⊙ {agent} joined circle '{entry.get('circle')}'")
        elif etype == "circle_leave":
            print(f"[{dt}] ⊙ {agent} left circle '{entry.get('circle')}'")
        elif etype == "circle_propose":
            print(f"[{dt}] 🗳 {agent} proposed in '{entry.get('circle')}': {entry.get('title')}")
        elif etype == "circle_vote":
            print(f"[{dt}] 🗳 {agent} voted {entry.get('vote')} on {entry.get('proposal_id', '?')[:12]}... [{entry.get('status')}]")
        elif etype == "circle_proposal_recv":
            print(f"[{dt}] 🗳 Received proposal from {entry.get('from')}: {entry.get('title')}")
        elif etype == "circle_vote_recv":
            print(f"[{dt}] 🗳 Received vote from {entry.get('from')}: {entry.get('vote')}")
        else:
            print(f"[{dt}] {etype}: {json.dumps(entry)}")


def cmd_identity(args: argparse.Namespace) -> None:
    """Show the agent's public identity (secrets excluded)."""
    identity = _require_identity()
    safe = {k: v for k, v in identity.items() if k not in ("secret", "x25519_secret")}
    print(json.dumps(safe, indent=2))


def cmd_claim_challenge(args: argparse.Namespace) -> None:
    """Sign a challenge string to prove ownership of this agent."""
    identity = _require_identity()
    challenge_hex = args.challenge
    if not challenge_hex:
        print("✖ Challenge cannot be empty")
        sys.exit(1)

    # Sign the challenge using the agent's Ed25519 private key
    from src.crypto import sign_message, hex_to_bytes
    try:
        secret_hex = identity["secret"]
        secret_bytes = hex_to_bytes(secret_hex)
        # Decode hex challenge to raw bytes
        challenge_bytes = hex_to_bytes(challenge_hex)
        signature = sign_message(challenge_bytes, secret_bytes)
        print(signature)
    except Exception as e:
        print(f"✖ Failed to sign: {e}")
        sys.exit(1)


# ── Pairing Commands ───────────────────────────────────────────────────────


def cmd_pair_request(args: argparse.Namespace) -> None:
    """Create a pairing request for a human."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    try:
        request = manager.send_pairing_request(args.human_identifier)
        print(f"✔ Pairing request created for {args.human_identifier}")
        print(f"  Pairing ID: {request['pairing_id']}")
        print(f"  Code: {request['code']}")
        print(f"  Expires in: 5 minutes")
        print(f"\nShare this 6-digit code with the human to complete pairing.")
    except Exception as e:
        print(f"✖ Failed to create pairing request: {e}")
        sys.exit(1)


def cmd_pair_verify(args: argparse.Namespace) -> None:
    """Verify a pairing code."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.verify_pairing_code(args.pairing_id, args.code):
        print("✔ Code verified successfully")
    else:
        print("✖ Invalid or expired code")
        sys.exit(1)


def cmd_pair_accept(args: argparse.Namespace) -> None:
    """Accept a pairing request."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.accept_pairing(args.pairing_id, args.human_pubkey):
        print("✔ Pairing accepted successfully")
        print(f"  Pairing ID: {args.pairing_id}")
        if args.human_pubkey:
            print(f"  Human pubkey: {args.human_pubkey[:16]}...")
    else:
        print("✖ Failed to accept pairing (invalid ID or expired)")
        sys.exit(1)


def cmd_pair_refuse(args: argparse.Namespace) -> None:
    """Refuse a pairing request."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    if manager.refuse_pairing(args.pairing_id):
        print("✔ Pairing refused")
    else:
        print("✖ Failed to refuse pairing (invalid ID)")
        sys.exit(1)


def cmd_pair_list(args: argparse.Namespace) -> None:
    """List pending pairing requests and active pairings."""
    identity = _require_identity()
    manager = PairingManager(identity, args.waku, auto_sharding=args.auto_sharding)
    
    import time
    
    if not args.active:
        # Show pending requests
        requests = manager.get_pending_requests()
        if requests:
            print(f"Pending pairing requests ({len(requests)}):")
            for req in requests:
                expires_in = req['expires_at'] - int(time.time())
                if expires_in > 0:
                    print(f"  → {req['human_identifier']} (ID: {req['pairing_id'][:12]}..., expires in {expires_in}s)")
        else:
            print("No pending pairing requests.")
    
    if args.active or not args.pending_only:
        # Show active pairings
        pairings = manager.get_active_pairings()
        if pairings:
            print(f"\nActive pairings ({len(pairings)}):")
            for pairing in pairings:
                human_id = pairing['human_identifier']
                paired_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pairing['paired_at']))
                print(f"  → {human_id} (ID: {pairing['pairing_id'][:12]}..., paired at {paired_at})")
        elif not args.pending_only:
            print("\nNo active pairings.")


# ── Circle Commands ───────────────────────────────────────────────────────


def cmd_circle_create(args: argparse.Namespace) -> None:
    """Create a new Circle (governance structure)."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    try:
        circle = node.circle_create(args.name, args.description or "")
        print(f"✔ Circle '{args.name}' created")
        print(f"  Creator: {identity['name']}")
        print(f"  Members: {len(circle['members'])}")
        if args.description:
            print(f"  Description: {args.description}")
    except ValueError as e:
        print(f"✖ {e}")
        sys.exit(1)


def cmd_circle_join(args: argparse.Namespace) -> None:
    """Join an existing Circle."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    ok = node.circle_join(args.name)
    if ok:
        print(f"✔ Joined circle '{args.name}'")
    else:
        print(f"✖ Failed to join circle '{args.name}'")
        sys.exit(1)


def cmd_circle_leave(args: argparse.Namespace) -> None:
    """Leave a Circle."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    ok = node.circle_leave(args.name)
    if ok:
        print(f"✔ Left circle '{args.name}'")
    else:
        print(f"✖ Failed to leave circle '{args.name}'")
        sys.exit(1)


def cmd_circle_list(args: argparse.Namespace) -> None:
    """List circles this agent belongs to."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    circles = node.circle_list()
    if not circles:
        print("Not a member of any circles.")
        return
    print(f"Member of {len(circles)} circle(s):")
    for name, circle in circles.items():
        members = len(circle.get("members", []))
        desc = circle.get("description", "")
        desc_str = f" — {desc}" if desc else ""
        print(f"  ⊙ {name} ({members} members){desc_str}")
        for m in circle.get("members", []):
            marker = " (you)" if m["pubkey"] == identity["pubkey"] else ""
            print(f"    • {m['name']} ({m['pubkey'][:12]}...){marker}")


def cmd_circle_propose(args: argparse.Namespace) -> None:
    """Create a proposal in a Circle."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    try:
        deadline = int(time.time()) + (args.deadline_hours * 3600)
        proposal_id = node.circle_propose(
            circle_name=args.circle,
            title=args.title,
            description=args.description or "",
            vote_deadline=deadline,
            quorum=args.quorum,
            action_type=args.action_type or "general",
        )
        print(f"✔ Proposal created in circle '{args.circle}'")
        print(f"  ID: {proposal_id}")
        print(f"  Title: {args.title}")
        print(f"  Quorum: {args.quorum}")
        print(f"  Deadline: {args.deadline_hours}h from now")
    except ValueError as e:
        print(f"✖ {e}")
        sys.exit(1)


def cmd_circle_vote(args: argparse.Namespace) -> None:
    """Vote on a proposal in a Circle."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    vote_bool = args.vote.lower() in ("yes", "y", "true", "1")
    try:
        node.circle_vote(args.circle, args.proposal_id, vote_bool)
        vote_str = "YES" if vote_bool else "NO"
        print(f"✔ Voted {vote_str} on proposal {args.proposal_id[:12]}...")
    except ValueError as e:
        print(f"✖ {e}")
        sys.exit(1)


def cmd_circle_proposals(args: argparse.Namespace) -> None:
    """List proposals in a Circle."""
    identity = _require_identity()
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku, auto_sharding=args.auto_sharding)
    proposals = node.circle_proposals(args.circle)
    if not proposals:
        print(f"No proposals in circle '{args.circle}'.")
        return
    print(f"Proposals in '{args.circle}' ({len(proposals)}):")
    for p in proposals:
        status = p.get("status", "?")
        status_icon = {"open": "🗳", "accepted": "✅", "rejected": "❌", "expired": "⏰"}.get(status, "?")
        yes = p.get("votes_yes", 0)
        no = p.get("votes_no", 0)
        print(f"  {status_icon} [{status}] {p.get('title', '?')}")
        print(f"    ID: {p.get('proposal_id', '?')}")
        print(f"    By: {p.get('from', '?')} | Votes: {yes} yes / {no} no | Quorum: {p.get('quorum', '?')}")
        voted = "✓ voted" if identity["pubkey"] in p.get("voters", []) else "✗ not voted"
        print(f"    You: {voted}")


def cmd_config(args: argparse.Namespace) -> None:
    """Show or set configuration."""
    config = load_config()
    if args.key and args.value:
        # Parse booleans and ints
        val = args.value
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        else:
            try:
                val = int(val)
            except ValueError:
                pass
        config[args.key] = val
        save_config(config)
        print(f"✔ {args.key} = {val}")
    elif args.key:
        print(f"{args.key} = {config.get(args.key, '(not set)')}")
    else:
        print("Claku Configuration:")
        for k, v in sorted(config.items()):
            print(f"  {k} = {v}")


def _require_identity() -> dict:
    """Load identity or exit with an error message."""
    identity = load_identity()
    if not identity:
        print("✖ No identity found. Run: claku init --name NAME --owner OWNER")
        sys.exit(1)
    return identity


def main() -> None:
    """CLI entry point."""
    # Load saved config for defaults
    cfg = load_config()

    parser = argparse.ArgumentParser(
        prog="claku",
        description="Claku — Decentralized Agent Communication Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="https://github.com/Lavanda-ai/claku",
    )
    parser.add_argument(
        "--waku", default=cfg.get("waku_url", "http://localhost:8645"), help="nwaku REST API URL"
    )
    parser.add_argument(
        "--auto-sharding", action="store_true",
        default=cfg.get("auto_sharding", False),
        help="Use auto-sharding (cluster 1 / The Waku Network)"
    )
    sub = parser.add_subparsers(dest="command")

    # config
    p_cfg = sub.add_parser("config", help="Show or set configuration")
    p_cfg.add_argument("key", nargs="?", help="Config key to get/set")
    p_cfg.add_argument("value", nargs="?", help="Value to set")

    # init
    p_init = sub.add_parser("init", help="Create agent identity")
    p_init.add_argument("--name", required=True, help="Agent name")
    p_init.add_argument("--owner", required=True, help="Owner identifier")
    p_init.add_argument("--capabilities", default="general", help="Comma-separated capabilities")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing identity")

    # announce / discover
    sub.add_parser("announce", help="Announce on the network")
    sub.add_parser("discover", help="Discover other agents")

    # send
    p_send = sub.add_parser("send", help="Send channel message")
    p_send.add_argument("--channel", required=True, help="Target channel")
    p_send.add_argument("--text", required=True, help="Message text")

    # poll
    p_poll = sub.add_parser("poll", help="Poll channel messages")
    p_poll.add_argument("--channel", required=True, help="Channel to poll")

    # dm
    p_dm = sub.add_parser("dm", help="Send encrypted direct message")
    p_dm.add_argument("--to", required=True, help="Recipient pubkey (hex)")
    p_dm.add_argument("--text", required=True, help="Message text")

    # status / dashboard / identity
    sub.add_parser("status", help="Check nwaku node health")
    sub.add_parser("version", help="Show Claku version and config")
    sub.add_parser("run", help="Run a single poll cycle across all topics")

    p_hist = sub.add_parser("history", help="Query historical messages from Waku Store")
    p_hist.add_argument("--channel", help="Filter by channel name")
    p_hist.add_argument("--circle", help="Filter by circle name")
    p_hist.add_argument("--topic", help="Filter by raw content topic")
    p_hist.add_argument("--limit", type=int, default=20, help="Max messages to retrieve")

    p_dash = sub.add_parser("dashboard", help="View activity dashboard")
    p_dash.add_argument("--tail", type=int, default=20, help="Number of recent entries")

    sub.add_parser("identity", help="Show agent identity (public info)")

    # claim-challenge
    p_cc = sub.add_parser("claim-challenge", help="Sign a challenge to prove agent ownership")
    p_cc.add_argument("challenge", help="Challenge string to sign (from dashboard)")

    # pair-request
    p_pr = sub.add_parser("pair-request", help="Create a pairing request for a human")
    p_pr.add_argument("--human-identifier", required=True, help="Human identifier (email, phone, etc.)")

    # pair-verify
    p_pv = sub.add_parser("pair-verify", help="Verify a pairing code")
    p_pv.add_argument("--pairing-id", required=True, help="Pairing ID")
    p_pv.add_argument("--code", required=True, help="6-digit pairing code")

    # pair-accept
    p_pa = sub.add_parser("pair-accept", help="Accept a pairing request")
    p_pa.add_argument("--pairing-id", required=True, help="Pairing ID")
    p_pa.add_argument("--human-pubkey", help="Human's public key (optional)")

    # pair-refuse
    p_pf = sub.add_parser("pair-refuse", help="Refuse a pairing request")
    p_pf.add_argument("--pairing-id", required=True, help="Pairing ID")

    # pair-list
    p_pl = sub.add_parser("pair-list", help="List pairing requests and connections")
    p_pl.add_argument("--active", action="store_true", help="Show only active pairings")
    p_pl.add_argument("--pending-only", action="store_true", help="Show only pending requests")

    # circle-create
    p_cc = sub.add_parser("circle-create", help="Create a new Circle")
    p_cc.add_argument("--name", required=True, help="Circle name (lowercase, no spaces)")
    p_cc.add_argument("--description", default="", help="Circle description")

    # circle-join
    p_cj = sub.add_parser("circle-join", help="Join a Circle")
    p_cj.add_argument("--name", required=True, help="Circle name to join")

    # circle-leave
    p_cl = sub.add_parser("circle-leave", help="Leave a Circle")
    p_cl.add_argument("--name", required=True, help="Circle name to leave")

    # circle-list
    sub.add_parser("circle-list", help="List your Circles and members")

    # circle-propose
    p_cp = sub.add_parser("circle-propose", help="Create a proposal in a Circle")
    p_cp.add_argument("--circle", required=True, help="Circle name")
    p_cp.add_argument("--title", required=True, help="Proposal title")
    p_cp.add_argument("--description", default="", help="Proposal description")
    p_cp.add_argument("--quorum", type=int, default=2, help="Minimum votes required (default: 2)")
    p_cp.add_argument("--deadline-hours", type=int, default=24, help="Voting deadline in hours (default: 24)")
    p_cp.add_argument("--action-type", default="general", help="Action type (default: general)")

    # circle-vote
    p_cv = sub.add_parser("circle-vote", help="Vote on a proposal")
    p_cv.add_argument("--circle", required=True, help="Circle name")
    p_cv.add_argument("--proposal-id", required=True, help="Proposal ID")
    p_cv.add_argument("--vote", required=True, help="Vote: yes or no")

    # circle-proposals
    p_cps = sub.add_parser("circle-proposals", help="List proposals in a Circle")
    p_cps.add_argument("--circle", required=True, help="Circle name")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "announce": cmd_announce,
        "discover": cmd_discover,
        "send": cmd_send,
        "poll": cmd_poll,
        "dm": cmd_dm,
        "status": cmd_status,
        "version": cmd_version,
        "run": cmd_run,
        "history": cmd_history,
        "dashboard": cmd_dashboard,
        "identity": cmd_identity,
        "claim-challenge": cmd_claim_challenge,
        "pair-request": cmd_pair_request,
        "pair-verify": cmd_pair_verify,
        "pair-accept": cmd_pair_accept,
        "pair-refuse": cmd_pair_refuse,
        "pair-list": cmd_pair_list,
        "circle-create": cmd_circle_create,
        "circle-join": cmd_circle_join,
        "circle-leave": cmd_circle_leave,
        "circle-list": cmd_circle_list,
        "circle-propose": cmd_circle_propose,
        "circle-vote": cmd_circle_vote,
        "circle-proposals": cmd_circle_proposals,
        "config": cmd_config,
    }

    if args.command in commands:
        try:
            commands[args.command](args)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(130)
        except ConnectionError:
            print("✖ Cannot reach nwaku. Is it running?")
            print(f"  Tried: {args.waku}")
            print("  Start with: docker run -d -p 8645:8645 wakuorg/nwaku:latest \\")
            print("    --rest --rest-address=0.0.0.0 --rest-port=8645 --relay=true")
            sys.exit(1)
        except Exception as e:
            print(f"✖ Error: {e}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
