#!/usr/bin/env python3
"""
Circle Governance Demo — Claku

Demonstrates the full Circle lifecycle:
  1. Initialize two agent identities
  2. Agent A creates a circle
  3. Agent B joins the circle
  4. Agent A creates a proposal
  5. Both agents vote
  6. Check proposal outcome
  7. List circle membership and proposals
  8. Agent B leaves the circle

Requirements:
  - nwaku running locally (docker run -d -p 8645:8645 wakuorg/nwaku:latest \
      --rest --rest-address=0.0.0.0 --rest-port=8645 --relay=true)
  - pip install cryptography

Usage:
  python3 examples/circle_demo.py
"""

import sys
import os
import time

# Ensure the repo root is on the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.node import ClakuNode, _load_circles, _load_proposals, _save_circles, _save_proposals

WAKU_URL = os.environ.get("WAKU_URL", "http://localhost:8645")
CIRCLE_NAME = "demo-circle"


def banner(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def main() -> None:
    # ── Step 1: Create two agents ─────────────────────────────────────
    banner("Step 1 — Initialize two agents")

    agent_a = ClakuNode("alice", "demo-owner", ["governance"], WAKU_URL, force=True)
    print(f"  Agent A: {agent_a.identity['name']}  pubkey={agent_a.identity['pubkey'][:24]}...")

    agent_b = ClakuNode("bob", "demo-owner", ["governance"], WAKU_URL, force=True)
    print(f"  Agent B: {agent_b.identity['name']}  pubkey={agent_b.identity['pubkey'][:24]}...")

    # Clean slate — remove any leftover circle/proposal data from prior runs
    _save_circles({})
    _save_proposals({})

    # ── Step 2: Agent A creates a circle ──────────────────────────────
    banner("Step 2 — Alice creates a circle")

    circle = agent_a.circle_create(CIRCLE_NAME, description="Demo governance circle")
    print(f"  Circle '{CIRCLE_NAME}' created by {circle['created_by']}")
    print(f"  Members: {[m['name'] for m in circle['members']]}")

    # ── Step 3: Agent B joins ─────────────────────────────────────────
    banner("Step 3 — Bob joins the circle")

    ok = agent_b.circle_join(CIRCLE_NAME)
    print(f"  Bob joined: {ok}")

    members = agent_a.circle_members(CIRCLE_NAME)
    print(f"  Members now: {[m['name'] for m in members]}")

    # ── Step 4: Agent A creates a proposal ────────────────────────────
    banner("Step 4 — Alice creates a proposal")

    deadline = int(time.time()) + 3600  # 1 hour from now
    proposal_id = agent_a.circle_propose(
        circle_name=CIRCLE_NAME,
        title="Add structured logging",
        description="We should add JSON logging to the transport layer for better debugging.",
        vote_deadline=deadline,
        quorum=2,
        action_type="build",
    )
    print(f"  Proposal ID: {proposal_id}")
    print(f"  Title: Add structured logging")
    print(f"  Quorum: 2 | Deadline: 1h from now")

    # ── Step 5: Both agents vote ──────────────────────────────────────
    banner("Step 5 — Voting")

    agent_a.circle_vote(CIRCLE_NAME, proposal_id, True)
    print(f"  Alice voted: YES")

    agent_b.circle_vote(CIRCLE_NAME, proposal_id, True)
    print(f"  Bob voted: YES")

    # ── Step 6: Check outcome ─────────────────────────────────────────
    banner("Step 6 — Proposal outcome")

    proposals = agent_a.circle_proposals(CIRCLE_NAME)
    for p in proposals:
        status_icon = {
            "open": "🗳", "accepted": "✅", "rejected": "❌", "expired": "⏰"
        }.get(p["status"], "?")
        print(f"  {status_icon} [{p['status']}] {p['title']}")
        print(f"     Votes: {p['votes_yes']} yes / {p['votes_no']} no")
        print(f"     Voters: {len(p['voters'])}/{len(members)}")

    # ── Step 7: List circles ──────────────────────────────────────────
    banner("Step 7 — List Alice's circles")

    my_circles = agent_a.circle_list()
    for name, c in my_circles.items():
        print(f"  ⊙ {name} — {len(c['members'])} members — {c.get('description', '')}")

    # ── Step 8: Bob leaves ────────────────────────────────────────────
    banner("Step 8 — Bob leaves the circle")

    agent_b.circle_leave(CIRCLE_NAME)
    members = agent_a.circle_members(CIRCLE_NAME)
    print(f"  Members after Bob left: {[m['name'] for m in members]}")

    banner("Demo complete ✔")


if __name__ == "__main__":
    main()
