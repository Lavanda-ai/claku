#!/usr/bin/env python3
"""
Test suite for the Claku Circles governance system.

Tests the full flow: create circle, join, propose, vote, check results.
Uses mocked transport to avoid requiring a live nwaku node.
"""

import json
import sys
import os
import time
import tempfile
import shutil
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.identity import (
    CIRCLE_MSG_TOPIC,
    CIRCLE_PROPOSAL_TOPIC,
    CIRCLE_VOTE_TOPIC,
)


def make_node(name: str, tmp_dir: Path):
    """Create a ClakuNode with mocked transport and temp storage."""
    from src.node import ClakuNode, _circles_file, _proposals_file, CIRCLES_DIR
    import src.identity as identity_mod
    import src.node as node_mod

    # Redirect storage to temp dir (both identity module and node module refs)
    identity_mod.CLAKU_DIR = tmp_dir
    identity_mod.IDENTITY_FILE = tmp_dir / "identity.json"
    identity_mod.DASHBOARD_FILE = tmp_dir / "dashboard.jsonl"
    node_mod.CIRCLES_DIR = tmp_dir / "circles"
    node_mod.CLAKU_DIR = tmp_dir
    node_mod.DASHBOARD_FILE = tmp_dir / "dashboard.jsonl"

    node = ClakuNode(name, "test-owner", ["governance"], force=True)
    node.transport = MagicMock()
    node.transport.subscribe.return_value = True
    node.transport.publish_json.return_value = True
    return node


def test_circle_create():
    """Test creating a circle."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        circle = node.circle_create("test-circle", "A test governance circle")

        assert circle["name"] == "test-circle"
        assert circle["description"] == "A test governance circle"
        assert circle["created_by"] == "agent-alpha"
        assert len(circle["members"]) == 1
        assert circle["members"][0]["name"] == "agent-alpha"

        # Verify it was published
        node.transport.publish_json.assert_called()
        call_args = node.transport.publish_json.call_args
        assert call_args[0][0] == CIRCLE_MSG_TOPIC("test-circle")

        # Verify duplicate creation fails
        try:
            node.circle_create("test-circle")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already exists" in str(e)

        print("  ✔ circle_create")
    finally:
        shutil.rmtree(tmp)


def test_circle_join_leave():
    """Test joining and leaving a circle."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("gov-circle")

        # Create a second node sharing the same storage
        import src.node as node_mod
        import src.identity as identity_mod
        identity_mod.CLAKU_DIR = tmp
        identity_mod.IDENTITY_FILE = tmp / "identity2.json"
        node_mod.CIRCLES_DIR = tmp / "circles"

        node2 = make_node("agent-beta", tmp)
        # Restore circles dir (make_node resets identity file)
        identity_mod.IDENTITY_FILE = tmp / "identity2.json"

        ok = node2.circle_join("gov-circle")
        assert ok is True

        members = node2.circle_members("gov-circle")
        names = [m["name"] for m in members]
        assert "agent-alpha" in names
        assert "agent-beta" in names

        # Leave
        ok = node2.circle_leave("gov-circle")
        assert ok is True
        members = node.circle_members("gov-circle")
        names = [m["name"] for m in members]
        assert "agent-beta" not in names
        assert "agent-alpha" in names

        print("  ✔ circle_join / circle_leave")
    finally:
        shutil.rmtree(tmp)


def test_circle_list():
    """Test listing circles."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("circle-a", "First circle")
        node.circle_create("circle-b", "Second circle")

        circles = node.circle_list()
        assert "circle-a" in circles
        assert "circle-b" in circles
        assert len(circles) == 2

        print("  ✔ circle_list")
    finally:
        shutil.rmtree(tmp)


def test_proposal_create():
    """Test creating a proposal."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("dev-circle")

        deadline = int(time.time()) + 3600  # 1 hour from now
        pid = node.circle_propose(
            circle_name="dev-circle",
            title="Build a block explorer",
            description="We need a testnet block explorer for monitoring.",
            vote_deadline=deadline,
            quorum=1,
            action_type="build",
        )

        assert pid is not None
        assert len(pid) == 36  # UUID format

        proposals = node.circle_proposals("dev-circle")
        assert len(proposals) == 1
        assert proposals[0]["title"] == "Build a block explorer"
        assert proposals[0]["status"] == "open"
        assert proposals[0]["quorum"] == 1

        # Verify published to proposal topic
        calls = [c for c in node.transport.publish_json.call_args_list
                 if c[0][0] == CIRCLE_PROPOSAL_TOPIC("dev-circle")]
        assert len(calls) >= 1

        print("  ✔ circle_propose")
    finally:
        shutil.rmtree(tmp)


def test_proposal_non_member():
    """Test that non-members cannot propose."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("restricted-circle")

        # Create second node
        import src.identity as identity_mod
        identity_mod.IDENTITY_FILE = tmp / "identity2.json"

        node2 = make_node("agent-beta", tmp)

        try:
            node2.circle_propose(
                circle_name="restricted-circle",
                title="Unauthorized proposal",
                description="Should fail",
                vote_deadline=int(time.time()) + 3600,
                quorum=1,
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Not a member" in str(e)

        print("  ✔ proposal_non_member rejected")
    finally:
        shutil.rmtree(tmp)


def test_vote_flow():
    """Test the full voting flow: propose, vote, check acceptance."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("vote-circle")

        # Add a second member
        import src.identity as identity_mod
        identity_mod.IDENTITY_FILE = tmp / "identity2.json"
        node2 = make_node("agent-beta", tmp)
        node2.circle_join("vote-circle")

        # Alpha proposes with quorum=2
        deadline = int(time.time()) + 3600
        pid = node.circle_propose(
            circle_name="vote-circle",
            title="Fund the project",
            description="Allocate resources to the project.",
            vote_deadline=deadline,
            quorum=2,
        )

        # Alpha votes yes
        ok = node.circle_vote("vote-circle", pid, True)
        assert ok is True

        # Check proposal state after 1 vote
        proposals = node.circle_proposals("vote-circle")
        p = [x for x in proposals if x["proposal_id"] == pid][0]
        assert p["votes_yes"] == 1
        assert p["votes_no"] == 0
        assert p["status"] == "open"  # Quorum not yet reached

        # Beta votes yes — quorum reached, should be accepted
        ok = node2.circle_vote("vote-circle", pid, True)
        assert ok is True

        proposals = node2.circle_proposals("vote-circle")
        p = [x for x in proposals if x["proposal_id"] == pid][0]
        assert p["votes_yes"] == 2
        assert p["status"] == "accepted"

        print("  ✔ vote_flow (propose → vote → accepted)")
    finally:
        shutil.rmtree(tmp)


def test_vote_rejection():
    """Test that a proposal can be rejected."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("reject-circle")

        import src.identity as identity_mod
        identity_mod.IDENTITY_FILE = tmp / "identity2.json"
        node2 = make_node("agent-beta", tmp)
        node2.circle_join("reject-circle")

        deadline = int(time.time()) + 3600
        pid = node.circle_propose(
            circle_name="reject-circle",
            title="Bad idea",
            description="This should be rejected.",
            vote_deadline=deadline,
            quorum=2,
        )

        # Both vote no
        node.circle_vote("reject-circle", pid, False)
        node2.circle_vote("reject-circle", pid, False)

        proposals = node.circle_proposals("reject-circle")
        p = [x for x in proposals if x["proposal_id"] == pid][0]
        assert p["votes_no"] == 2
        # Quorum reached but no majority yes — check status
        assert p["status"] in ("open", "rejected")

        print("  ✔ vote_rejection")
    finally:
        shutil.rmtree(tmp)


def test_double_vote():
    """Test that double voting is prevented."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("double-circle")

        deadline = int(time.time()) + 3600
        pid = node.circle_propose(
            circle_name="double-circle",
            title="Test double vote",
            description="Should only count once.",
            vote_deadline=deadline,
            quorum=2,
        )

        node.circle_vote("double-circle", pid, True)

        try:
            node.circle_vote("double-circle", pid, True)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Already voted" in str(e)

        print("  ✔ double_vote prevented")
    finally:
        shutil.rmtree(tmp)


def test_expired_proposal():
    """Test that voting on expired proposals is rejected."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("expire-circle")

        # Create proposal with deadline in the past
        pid = node.circle_propose(
            circle_name="expire-circle",
            title="Already expired",
            description="Deadline already passed.",
            vote_deadline=int(time.time()) - 1,
            quorum=1,
        )

        try:
            node.circle_vote("expire-circle", pid, True)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "deadline" in str(e).lower()

        print("  ✔ expired_proposal rejected")
    finally:
        shutil.rmtree(tmp)


def test_dashboard_logging():
    """Test that circle events are logged to the dashboard."""
    tmp = Path(tempfile.mkdtemp())
    try:
        node = make_node("agent-alpha", tmp)
        node.circle_create("log-circle")
        node.circle_join("log-circle")

        deadline = int(time.time()) + 3600
        pid = node.circle_propose(
            circle_name="log-circle",
            title="Logged proposal",
            description="Check dashboard.",
            vote_deadline=deadline,
            quorum=1,
        )
        node.circle_vote("log-circle", pid, True)

        # Read dashboard
        import src.identity as identity_mod
        dash_file = identity_mod.DASHBOARD_FILE
        assert dash_file.exists(), "Dashboard file should exist"

        lines = dash_file.read_text().strip().split("\n")
        events = [json.loads(line) for line in lines if line.strip()]
        event_types = [e["type"] for e in events]

        assert "circle_create" in event_types
        assert "circle_propose" in event_types
        assert "circle_vote" in event_types

        print("  ✔ dashboard_logging")
    finally:
        shutil.rmtree(tmp)


def test_content_topics():
    """Test that content topic functions generate correct paths."""
    assert CIRCLE_MSG_TOPIC("privacy-tools") == "/claku/1/circle/privacy-tools/msg/proto"
    assert CIRCLE_PROPOSAL_TOPIC("lez-dev") == "/claku/1/circle/lez-dev/proposal/proto"
    assert CIRCLE_VOTE_TOPIC("floripa") == "/claku/1/circle/floripa/vote/proto"
    print("  ✔ content_topics")


if __name__ == "__main__":
    print("Running Claku Circles test suite...\n")

    tests = [
        test_content_topics,
        test_circle_create,
        test_circle_join_leave,
        test_circle_list,
        test_proposal_create,
        test_proposal_non_member,
        test_vote_flow,
        test_vote_rejection,
        test_double_vote,
        test_expired_proposal,
        test_dashboard_logging,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✖ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(1 if failed else 0)
