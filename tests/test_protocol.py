#!/usr/bin/env python3
"""Tests for Claku signing, pairing, and connections."""

import sys, os, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crypto import generate_ed25519_keypair, generate_x25519_keypair, bytes_to_hex
from src.signing import sign_msg, validate_msg, _seen_ids
from src.pairing import PairingManager
from src.connections import ConnectionManager, UNKNOWN, SEEN, CONTACTED, TRUSTED


class TestSigning(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = generate_ed25519_keypair()
        self.priv_hex = bytes_to_hex(self.priv)
        self.pub_hex = bytes_to_hex(self.pub)
        _seen_ids.clear()

    def test_sign_and_validate_channel_msg(self):
        msg = {
            "type": "channel_msg",
            "channel": "#general",
            "from_pubkey": self.pub_hex,
            "text": "hello world",
        }
        signed = sign_msg(msg, self.priv_hex)
        self.assertIn("signature", signed)
        self.assertIn("msg_id", signed)
        self.assertIn("protocol", signed)
        self.assertEqual(signed["protocol"], "claku/1.0")

        valid, reason = validate_msg(signed)
        self.assertTrue(valid, reason)

    def test_sign_and_validate_agent_card(self):
        msg = {
            "type": "agent_card",
            "name": "test-agent",
            "pubkey": self.pub_hex,
            "from_pubkey": self.pub_hex,
            "capabilities": ["chat", "code"],
        }
        signed = sign_msg(msg, self.priv_hex)
        valid, reason = validate_msg(signed)
        self.assertTrue(valid, reason)

    def test_reject_unsigned(self):
        msg = {"type": "channel_msg", "from_pubkey": self.pub_hex, "text": "no sig"}
        valid, reason = validate_msg(msg)
        self.assertFalse(valid)
        self.assertEqual(reason, "missing signature")

    def test_reject_tampered(self):
        msg = {
            "type": "channel_msg",
            "channel": "#general",
            "from_pubkey": self.pub_hex,
            "text": "original",
        }
        signed = sign_msg(msg, self.priv_hex)
        signed["text"] = "tampered"
        valid, reason = validate_msg(signed)
        self.assertFalse(valid)

    def test_reject_wrong_key(self):
        other_priv, other_pub = generate_ed25519_keypair()
        msg = {
            "type": "channel_msg",
            "channel": "#general",
            "from_pubkey": self.pub_hex,
            "text": "hello",
        }
        signed = sign_msg(msg, bytes_to_hex(other_priv))
        valid, reason = validate_msg(signed)
        self.assertFalse(valid)

    def test_reject_old_message(self):
        msg = {
            "type": "channel_msg",
            "from_pubkey": self.pub_hex,
            "text": "old",
            "ts": int(time.time()) - 90000,
        }
        signed = sign_msg(msg, self.priv_hex)
        signed["ts"] = int(time.time()) - 90000  # override ts after signing
        valid, reason = validate_msg(signed)
        self.assertIn("too old", reason)

    def test_connection_request_signing(self):
        msg = {
            "type": "connection_request",
            "from_pubkey": self.pub_hex,
            "to": "deadbeef",
            "reason": "want to collaborate",
        }
        signed = sign_msg(msg, self.priv_hex)
        valid, reason = validate_msg(signed)
        self.assertTrue(valid, reason)


class TestPairing(unittest.TestCase):
    def setUp(self):
        self.pm = PairingManager()
        self.pm.pairings = {}
        self.pm.pending = {}

    def test_create_offer(self):
        offer = self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        self.assertEqual(len(offer["code"]), 6)
        self.assertTrue(offer["code"].isdigit())
        self.assertIn("eph_public", offer)
        self.assertIn("expires", offer)

    def test_accept_valid_code(self):
        offer = self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        _, human_pub = generate_x25519_keypair()
        result = self.pm.accept_offer(offer["code"], bytes_to_hex(human_pub))
        self.assertIsNotNone(result)
        self.assertIn("shared_secret", result)
        self.assertIn("paired_at", result)

    def test_reject_wrong_code(self):
        self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        _, human_pub = generate_x25519_keypair()
        result = self.pm.accept_offer("000000", bytes_to_hex(human_pub))
        self.assertIsNone(result)

    def test_reject_expired_code(self):
        offer = self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        # Force expire
        self.pm.pending[offer["code"]]["expires"] = int(time.time()) - 1
        _, human_pub = generate_x25519_keypair()
        result = self.pm.accept_offer(offer["code"], bytes_to_hex(human_pub))
        self.assertIsNone(result)

    def test_code_single_use(self):
        offer = self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        _, human_pub = generate_x25519_keypair()
        result1 = self.pm.accept_offer(offer["code"], bytes_to_hex(human_pub))
        self.assertIsNotNone(result1)
        result2 = self.pm.accept_offer(offer["code"], bytes_to_hex(human_pub))
        self.assertIsNone(result2)

    def test_revoke_pairing(self):
        offer = self.pm.create_offer("agent_pub_123", "agent_x25519_123")
        _, human_pub = generate_x25519_keypair()
        human_hex = bytes_to_hex(human_pub)
        self.pm.accept_offer(offer["code"], human_hex)
        self.assertTrue(self.pm.is_paired(human_hex))
        self.pm.revoke(human_hex)
        self.assertFalse(self.pm.is_paired(human_hex))


class TestConnections(unittest.TestCase):
    def setUp(self):
        self.cm = ConnectionManager()
        self.cm.connections = {}

    def test_initial_trust_unknown(self):
        self.assertEqual(self.cm.get_trust("abc123"), UNKNOWN)

    def test_on_agent_seen(self):
        self.cm.on_agent_seen("abc123", "test-agent", ["chat"])
        self.assertEqual(self.cm.get_trust("abc123"), SEEN)
        conn = self.cm.connections["abc123"]
        self.assertEqual(conn["name"], "test-agent")

    def test_accept_connection(self):
        self.cm.accept_connection("abc123", "test-agent")
        self.assertEqual(self.cm.get_trust("abc123"), CONTACTED)

    def test_trust_doesnt_downgrade(self):
        self.cm.accept_connection("abc123", "test-agent")
        self.cm.on_agent_seen("abc123", "test-agent")
        self.assertEqual(self.cm.get_trust("abc123"), CONTACTED)

    def test_promote_to_trusted(self):
        self.cm.accept_connection("abc123", "test-agent")
        self.cm.promote_to_trusted("abc123")
        self.assertEqual(self.cm.get_trust("abc123"), TRUSTED)

    def test_revoke_trust(self):
        self.cm.accept_connection("abc123", "test-agent")
        self.cm.revoke_trust("abc123")
        self.assertEqual(self.cm.get_trust("abc123"), UNKNOWN)

    def test_auto_accept_by_trust(self):
        self.cm.auto_rules["require_trust_level"] = SEEN
        self.cm.on_agent_seen("abc123", "test-agent")
        self.assertTrue(self.cm.should_auto_accept("abc123"))

    def test_auto_accept_requires_human(self):
        self.cm.auto_rules["require_human_approval"] = True
        self.cm.on_agent_seen("abc123", "test-agent")
        self.assertFalse(self.cm.should_auto_accept("abc123"))

    def test_list_connections(self):
        self.cm.on_agent_seen("a", "agent-a")
        self.cm.accept_connection("b", "agent-b")
        seen = self.cm.list_connections(min_trust=SEEN)
        self.assertEqual(len(seen), 2)
        contacted = self.cm.list_connections(min_trust=CONTACTED)
        self.assertEqual(len(contacted), 1)


if __name__ == "__main__":
    unittest.main()
