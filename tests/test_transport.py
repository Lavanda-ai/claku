#!/usr/bin/env python3
"""Tests for Claku transport layer — WakuTransport static + auto-sharding."""

import sys, os, json, base64, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.transport import WakuTransport, PUBSUB_TOPIC


class TestTransportInit(unittest.TestCase):
    def test_default_static(self):
        t = WakuTransport()
        self.assertEqual(t.waku_url, "https://node.claku.xyz")
        self.assertFalse(t.auto_sharding)

    def test_auto_sharding(self):
        t = WakuTransport("http://example:8645", auto_sharding=True)
        self.assertTrue(t.auto_sharding)

    def test_strips_trailing_slash(self):
        t = WakuTransport("http://localhost:8645/")
        self.assertEqual(t.waku_url, "http://localhost:8645")


class TestTopicEncoding(unittest.TestCase):
    def test_encode_topic(self):
        t = WakuTransport()
        encoded = t._encode_topic("/claku/1/discovery/proto")
        self.assertEqual(encoded, "%2Fclaku%2F1%2Fdiscovery%2Fproto")

    def test_encode_preserves_safe_chars(self):
        t = WakuTransport()
        encoded = t._encode_topic("simple")
        self.assertEqual(encoded, "simple")


class TestStaticSharding(unittest.TestCase):
    """Test path construction for static sharding (cluster 0)."""

    def test_subscribe_path(self):
        t = WakuTransport()
        with patch.object(t, '_request', return_value=(200, "OK")) as mock:
            result = t.subscribe()
            mock.assert_called_once_with("POST", "/relay/v1/subscriptions", [PUBSUB_TOPIC])
            self.assertTrue(result)

    def test_publish_path(self):
        t = WakuTransport()
        encoded_pubsub = t._encode_topic(PUBSUB_TOPIC)
        with patch.object(t, '_request', return_value=(200, "")) as mock:
            result = t.publish("/claku/1/test/proto", b"hello")
            call_args = mock.call_args
            self.assertEqual(call_args[0][0], "POST")
            self.assertIn(f"/relay/v1/messages/{encoded_pubsub}", call_args[0][1])
            self.assertTrue(result)

    def test_poll_path(self):
        t = WakuTransport()
        encoded_pubsub = t._encode_topic(PUBSUB_TOPIC)
        with patch.object(t, '_request', return_value=(200, "[]")) as mock:
            t.poll("/claku/1/test/proto")
            call_args = mock.call_args
            self.assertIn(f"/relay/v1/messages/{encoded_pubsub}", call_args[0][1])


class TestAutoSharding(unittest.TestCase):
    """Test path construction for auto-sharding (cluster 1+)."""

    def test_subscribe_path(self):
        t = WakuTransport(auto_sharding=True)
        with patch.object(t, '_request', return_value=(200, "OK")) as mock:
            result = t.subscribe("/claku/1/discovery/proto")
            mock.assert_called_once_with("POST", "/relay/v1/auto/subscriptions", ["/claku/1/discovery/proto"])
            self.assertTrue(result)

    def test_publish_path(self):
        t = WakuTransport(auto_sharding=True)
        with patch.object(t, '_request', return_value=(200, "")) as mock:
            result = t.publish("/claku/1/test/proto", b"hello")
            call_args = mock.call_args
            self.assertEqual(call_args[0][1], "/relay/v1/auto/messages")
            self.assertTrue(result)

    def test_poll_path(self):
        t = WakuTransport(auto_sharding=True)
        encoded = t._encode_topic("/claku/1/test/proto")
        with patch.object(t, '_request', return_value=(200, "[]")) as mock:
            t.poll("/claku/1/test/proto")
            call_args = mock.call_args
            self.assertIn(f"/relay/v1/auto/messages/{encoded}", call_args[0][1])

    def test_poll_no_topic_returns_empty(self):
        t = WakuTransport(auto_sharding=True)
        result = t.poll()
        self.assertEqual(result, [])


class TestPublishJson(unittest.TestCase):
    def test_publish_json_encodes(self):
        t = WakuTransport()
        with patch.object(t, 'publish', return_value=True) as mock:
            data = {"name": "lavanda", "type": "announce"}
            result = t.publish_json("/claku/1/discovery/proto", data)
            self.assertTrue(result)
            call_args = mock.call_args
            payload = call_args[0][1]
            self.assertEqual(json.loads(payload), data)


class TestPollJson(unittest.TestCase):
    def test_poll_json_parses(self):
        t = WakuTransport()
        msg_data = {"name": "lavanda"}
        raw_msg = [{
            "contentTopic": "/claku/1/discovery/proto",
            "payload": base64.b64encode(json.dumps(msg_data).encode()).decode(),
            "timestamp": 123456,
        }]
        with patch.object(t, '_request', return_value=(200, json.dumps(raw_msg))):
            results = t.poll_json("/claku/1/discovery/proto")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "lavanda")
            self.assertEqual(results[0]["_content_topic"], "/claku/1/discovery/proto")

    def test_poll_json_skips_invalid(self):
        t = WakuTransport()
        raw_msg = [{
            "contentTopic": "/claku/1/test/proto",
            "payload": base64.b64encode(b"not json").decode(),
            "timestamp": 123,
        }]
        with patch.object(t, '_request', return_value=(200, json.dumps(raw_msg))):
            results = t.poll_json("/claku/1/test/proto")
            self.assertEqual(len(results), 0)


class TestHealth(unittest.TestCase):
    def test_health_ok(self):
        t = WakuTransport()
        health_resp = '{"nodeHealth":"READY","connectionStatus":"Connected"}'
        with patch.object(t, '_request', return_value=(200, health_resp)):
            result = t.health()
            self.assertEqual(result["nodeHealth"], "READY")

    def test_health_error(self):
        t = WakuTransport()
        with patch.object(t, '_request', return_value=(500, "Internal error")):
            result = t.health()
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
