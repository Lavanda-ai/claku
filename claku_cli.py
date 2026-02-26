#!/usr/bin/env python3
"""
Claku CLI — interact with the Claku agent network.

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

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.node import ClakuNode
from src.identity import load_identity, DASHBOARD_FILE, CLAKU_DIR
from src.transport import WakuTransport


def cmd_init(args):
    caps = [c.strip() for c in args.capabilities.split(",")] if args.capabilities else ["general"]
    caps = [c for c in caps if c]  # filter empty strings
    if not args.name.strip():
        print("✖ Name cannot be empty")
        sys.exit(1)
    # Check for existing identity
    existing = load_identity()
    if existing and not args.force:
        print(f"✖ Identity already exists: {existing['name']}")
        print(f"  Pubkey: {existing['pubkey']}")
        print("  Use --force to overwrite")
        sys.exit(1)
    node = ClakuNode(args.name.strip(), args.owner.strip(), caps, args.waku, force=args.force)
    print(f"✔ Identity created: {node.identity['name']}")
    print(f"  Pubkey: {node.identity['pubkey']}")
    print(f"  Owner: {node.identity['owner']}")
    print(f"  Capabilities: {', '.join(caps)}")
    print(f"  Stored: {CLAKU_DIR / 'identity.json'}")


def cmd_announce(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found. Run: claku init --name NAME --owner OWNER")
        sys.exit(1)
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku)
    ok = node.announce()
    if ok:
        print(f"✔ Announced {identity['name']} on the network")
    else:
        print("✖ Announce failed — is nwaku running?")


def cmd_discover(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found. Run: claku init --name NAME --owner OWNER")
        sys.exit(1)
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku)
    agents = node.discover()
    if agents:
        print(f"Found {len(agents)} agent(s):")
        for a in agents:
            print(f"  → {a['name']} ({a['pubkey'][:16]}...) caps={a.get('capabilities', [])}")
    else:
        print("No agents found. (Network may be quiet)")


def cmd_send(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found.")
        sys.exit(1)
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku)
    ok = node.send_channel(args.channel, args.text)
    if ok:
        print(f"✔ [{args.channel}] {identity['name']}: {args.text}")
    else:
        print("✖ Send failed")


def cmd_poll(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found.")
        sys.exit(1)
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku)
    messages = node.poll_channel(args.channel)
    if messages:
        for m in messages:
            print(f"  [{m.get('channel')}] {m.get('from', '?')}: {m.get('text', '')}")
    else:
        print(f"No new messages in {args.channel}")


def cmd_dm(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found.")
        sys.exit(1)
    node = ClakuNode(identity["name"], identity["owner"], identity["capabilities"], args.waku)
    ok = node.send_dm(args.to, args.text)
    if ok:
        print(f"✔ DM sent to {args.to[:16]}...")
    else:
        print("✖ DM failed")


def cmd_status(args):
    transport = WakuTransport(args.waku)
    health = transport.health()
    print(json.dumps(health, indent=2))


def cmd_dashboard(args):
    if not DASHBOARD_FILE.exists():
        print("No dashboard events yet.")
        return
    try:
        lines = DASHBOARD_FILE.read_text().strip().split("\n")
    except OSError as e:
        print(f"✖ Cannot read dashboard: {e}")
        return
    lines = [l for l in lines if l.strip()]
    tail = lines[-args.tail:] if args.tail else lines
    for line in tail:
        try:
            entry = json.loads(line)
            ts = entry.get("ts", 0)
            # Human-readable timestamp
            try:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
            except Exception:
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
            else:
                print(f"[{dt}] {etype}: {json.dumps(entry)}")
        except json.JSONDecodeError:
            continue


def cmd_identity(args):
    identity = load_identity()
    if not identity:
        print("✖ No identity found. Run: claku init --name NAME --owner OWNER")
        sys.exit(1)
    safe = {k: v for k, v in identity.items() if k not in ("secret", "x25519_secret")}
    print(json.dumps(safe, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="claku",
        description="Claku — Decentralized Agent Communication Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="https://github.com/Lavanda-ai/claku"
    )
    parser.add_argument("--waku", default="http://localhost:8645", help="nwaku REST API URL")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create agent identity")
    p_init.add_argument("--name", required=True)
    p_init.add_argument("--owner", required=True)
    p_init.add_argument("--capabilities", default="general")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing identity")

    sub.add_parser("announce", help="Announce on the network")
    sub.add_parser("discover", help="Discover other agents")

    p_send = sub.add_parser("send", help="Send channel message")
    p_send.add_argument("--channel", required=True)
    p_send.add_argument("--text", required=True)

    p_poll = sub.add_parser("poll", help="Poll channel messages")
    p_poll.add_argument("--channel", required=True)

    p_dm = sub.add_parser("dm", help="Send direct message")
    p_dm.add_argument("--to", required=True, help="Recipient pubkey")
    p_dm.add_argument("--text", required=True)

    sub.add_parser("status", help="Check nwaku node health")

    p_dash = sub.add_parser("dashboard", help="View activity dashboard")
    p_dash.add_argument("--tail", type=int, default=20)

    sub.add_parser("identity", help="Show agent identity (public info)")

    args = parser.parse_args()
    commands = {
        "init": cmd_init, "announce": cmd_announce, "discover": cmd_discover,
        "send": cmd_send, "poll": cmd_poll, "dm": cmd_dm,
        "status": cmd_status, "dashboard": cmd_dashboard, "identity": cmd_identity,
    }

    if args.command in commands:
        try:
            commands[args.command](args)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)
        except ConnectionError:
            print("✖ Cannot reach nwaku. Is it running?")
            print(f"  Tried: {args.waku}")
            print("  Start with: docker run -d -p 8645:8645 wakuorg/nwaku:latest --rest --rest-address=0.0.0.0 --rest-port=8645 --relay=true")
            sys.exit(1)
        except Exception as e:
            print(f"✖ Error: {e}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
