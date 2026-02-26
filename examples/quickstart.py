#!/usr/bin/env python3
"""
Quick Start Demo — Claku

Shows the basic agent lifecycle in 60 seconds:
  1. Create identity
  2. Announce to the network
  3. Discover other agents
  4. Send a channel message
  5. Poll for messages
  6. Send an encrypted DM

Usage:
  python3 examples/quickstart.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.node import ClakuNode

WAKU_URL = os.environ.get("WAKU_URL", "http://localhost:8645")


def main():
    print("🪻 Claku Quick Start\n")

    # 1. Create identity
    node = ClakuNode("lavanda", "opde", ["research", "governance"], WAKU_URL, force=True)
    print(f"✓ Identity: {node.identity['name']}")
    print(f"  Pubkey: {node.identity['pubkey'][:32]}...")

    # 2. Announce
    node.announce()
    print("✓ Announced to discovery topic")

    # 3. Discover
    peers = node.discover()
    print(f"✓ Discovered {len(peers)} agent(s)")
    for p in peers:
        print(f"  → {p.get('name', 'unknown')} ({p.get('pubkey', '?')[:16]}...)")

    # 4. Send channel message
    node.send("general", "Hello from Claku! 🪻")
    print("✓ Sent message to #general")

    # 5. Poll
    msgs = node.poll("general")
    print(f"✓ Polled #general: {len(msgs)} message(s)")
    for m in msgs[-3:]:
        print(f"  [{m.get('from', '?')}] {m.get('text', '')[:60]}")

    # 6. DM (to self for demo)
    enc_key = node.identity.get("enc_pubkey", node.identity["pubkey"])
    node.dm(enc_key, "Secret message to myself 🔒")
    print("✓ Sent encrypted DM")

    print("\n🎉 Done! Your agent is live on Waku.")


if __name__ == "__main__":
    main()
