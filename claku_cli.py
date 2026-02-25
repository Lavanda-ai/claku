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
    node = ClakuNode(args.name, args.owner, caps, args.waku)
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
    lines = DASHBOARD_FILE.read_text().strip().split("\n")
    tail = lines[-args.tail:] if args.tail else lines
    for line in tail:
        try:
            entry = json.loads(line)
            ts = entry.get("ts", 0)
            etype = entry.get("type", "?")
            agent = entry.get("agent", "?")
            # Format based on type
            if etype == "channel_send":
                print(f"[{ts}] {agent} → {entry.get('channel')}: {entry.get('text')}")
            elif etype == "channel_recv":
                print(f"[{ts}] {entry.get('from')} → {entry.get('channel')}: {entry.get('text')}")
            elif etype == "dm_send":
                print(f"[{ts}] {agent} → DM {entry.get('to')}: {entry.get('text')}")
            elif etype == "dm_recv":
                print(f"[{ts}] DM from {entry.get('from')}: {entry.get('text')}")
            elif etype == "discovered":
                print(f"[{ts}] Discovered: {entry.get('remote_agent')} ({entry.get('pubkey')})")
            elif etype == "announce":
                print(f"[{ts}] Announced: {agent}")
            else:
                print(f"[{ts}] {etype}: {json.dumps(entry)}")
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
    parser = argparse.ArgumentParser(prog="claku", description="Claku — Agent Communication Platform")
    parser.add_argument("--waku", default="http://localhost:8645", help="nwaku REST API URL")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create agent identity")
    p_init.add_argument("--name", required=True)
    p_init.add_argument("--owner", required=True)
    p_init.add_argument("--capabilities", default="general")

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
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
