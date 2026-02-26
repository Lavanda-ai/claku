#!/usr/bin/env python3
"""
Integration test — Claku on The Waku Network (cluster 1).

Tests real network operations against a live nwaku node.
Requires nwaku running on localhost:8645 with cluster 1.

Usage:
    python3 tests/test_integration.py
"""

import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.transport import WakuTransport
from src.node import ClakuNode
from src.config import load_config

WAKU_URL = os.environ.get("WAKU_URL", "http://localhost:8645")
PASS = 0
FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  ✔ {name}")
        PASS += 1
    except Exception as e:
        print(f"  ✖ {name}: {e}")
        FAIL += 1


def test_health():
    t = WakuTransport(WAKU_URL)
    h = t.health()
    assert h.get("nodeHealth") == "READY", f"Expected READY, got {h}"


def test_health_connected():
    t = WakuTransport(WAKU_URL)
    h = t.health()
    status = h.get("connectionStatus", "")
    assert status == "Connected", f"Expected Connected, got {status}"


def test_auto_subscribe():
    t = WakuTransport(WAKU_URL, auto_sharding=True)
    status, body = t._request('POST', '/relay/v1/auto/subscriptions',
                              ['/claku/1/test/integration/proto'])
    assert status == 200, f"Subscribe failed with status {status}: {body}"


def test_auto_poll_empty():
    t = WakuTransport(WAKU_URL, auto_sharding=True)
    t.subscribe("/claku/1/test/poll-empty/proto")
    msgs = t.poll("/claku/1/test/poll-empty/proto")
    assert isinstance(msgs, list), f"Expected list, got {type(msgs)}"


def test_identity_creation():
    node = ClakuNode("integration-test", "test-owner", ["testing"], WAKU_URL,
                     force=True, auto_sharding=True)
    assert node.identity["name"] == "integration-test"
    assert "pubkey" in node.identity
    assert "x25519_pubkey" in node.identity
    assert len(node.identity["pubkey"]) == 64  # hex-encoded 32 bytes


def test_circle_lifecycle():
    from src.node import _load_circles, _save_circles, _load_proposals, _save_proposals
    # Clean up from previous runs
    circles = _load_circles()
    circles.pop("integration-test-circle", None)
    _save_circles(circles)
    proposals = _load_proposals()
    proposals.pop("integration-test-circle", None)
    _save_proposals(proposals)

    node = ClakuNode("circle-tester", "test", ["governance"], WAKU_URL,
                     force=True, auto_sharding=True)

    # Create
    circle = node.circle_create("integration-test-circle",
                                description="Testing circle lifecycle")
    assert circle["name"] == "integration-test-circle"
    assert len(circle["members"]) == 1

    # Propose
    deadline = int(time.time()) + 3600
    pid = node.circle_propose(
        "integration-test-circle",
        title="Test proposal",
        description="Integration test",
        vote_deadline=deadline,
        quorum=1,
    )
    assert pid is not None

    # Vote
    node.circle_vote("integration-test-circle", pid, True)

    # Check accepted
    proposals = node.circle_proposals("integration-test-circle")
    found = [p for p in proposals if p["proposal_id"] == pid]
    assert len(found) == 1
    assert found[0]["status"] == "accepted"

    # Leave
    node.circle_leave("integration-test-circle")


def test_agent_card():
    node = ClakuNode("card-tester", "test", ["research"], WAKU_URL,
                     force=True, auto_sharding=True)
    card = node.agent_card()
    assert card["name"] == "card-tester"
    assert "research" in card["capabilities"]
    assert "pubkey" in card


def test_config_roundtrip():
    from src.config import set_value, get
    set_value("_test_key", "test_value")
    assert get("_test_key") == "test_value"
    # Cleanup
    config = load_config()
    config.pop("_test_key", None)
    from src.config import save_config
    save_config(config)


def main():
    print(f"\n🧪 Claku Integration Tests (nwaku: {WAKU_URL})\n")

    # Check nwaku is reachable
    try:
        t = WakuTransport(WAKU_URL)
        h = t.health()
        if h.get("nodeHealth") != "READY":
            print(f"⚠ nwaku not ready: {h}")
            print("Start nwaku first: bash setup.sh")
            sys.exit(1)
    except Exception as e:
        print(f"✖ Cannot reach nwaku at {WAKU_URL}: {e}")
        sys.exit(1)

    print("  Network tests:")
    test("health check", test_health)
    test("connection status", test_health_connected)
    test("auto-sharding subscribe", test_auto_subscribe)
    test("auto-sharding poll (empty)", test_auto_poll_empty)

    print("\n  Identity tests:")
    test("identity creation", test_identity_creation)
    test("agent card", test_agent_card)

    print("\n  Circle tests:")
    test("circle lifecycle (create → propose → vote → accept → leave)", test_circle_lifecycle)

    print("\n  Config tests:")
    test("config roundtrip", test_config_roundtrip)

    print(f"\n{'─' * 40}")
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
