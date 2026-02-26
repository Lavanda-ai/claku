#!/usr/bin/env python3
"""
Claku — Waku Transport Layer.

Publish/subscribe/poll via the nwaku REST API.
All Claku messages flow through Waku content topics using relay protocol.
"""

import json
import time
import base64
import urllib.parse
import urllib.request
from typing import Optional

#: Default pubsub topic for Waku static sharding (cluster 0, shard 0).
PUBSUB_TOPIC: str = "/waku/2/rs/0/0"

#: HTTP request timeout in seconds.
REQUEST_TIMEOUT: int = 10


class WakuTransport:
    """Transport layer for Claku messaging via the nwaku REST API.

    Wraps publish, subscribe, and poll operations against a single nwaku node.
    All payloads are base64-encoded before transmission per the Waku REST spec.
    """

    def __init__(self, waku_url: str = "http://localhost:8645") -> None:
        self.waku_url: str = waku_url.rstrip("/")

    def _encode_topic(self, topic: str) -> str:
        """URL-encode a Waku topic for use in REST paths."""
        return urllib.parse.quote(topic, safe="")

    def _request(
        self, method: str, path: str, data: Optional[dict | list] = None
    ) -> tuple[int, str]:
        """Make an HTTP request to the nwaku REST API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g. ``/health``).
            data: JSON-serializable body, or ``None`` for bodyless requests.

        Returns:
            Tuple of (HTTP status code, response body as string).
            Returns ``(0, error_message)`` on unexpected failures.

        Raises:
            ConnectionError: If the nwaku node is unreachable.
        """
        url = f"{self.waku_url}{path}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode("utf-8")
            except Exception:
                return e.code, str(e)
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach nwaku at {self.waku_url}: {e.reason}"
            )
        except OSError as e:
            raise ConnectionError(
                f"Network error connecting to {self.waku_url}: {e}"
            )

    def health(self) -> dict:
        """Check nwaku node health.

        Returns:
            Parsed JSON health response, or a dict with ``error`` key on failure.
        """
        status, body = self._request("GET", "/health")
        if status == 200:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"status": status, "raw": body}
        return {"error": body, "status": status}

    def subscribe(self, pubsub_topic: str = PUBSUB_TOPIC) -> bool:
        """Subscribe to a pubsub topic for relay messages.

        Args:
            pubsub_topic: The pubsub topic string. Defaults to cluster 0, shard 0.

        Returns:
            ``True`` if the subscription succeeded.
        """
        status, _ = self._request(
            "POST", "/relay/v1/subscriptions", [pubsub_topic]
        )
        return status == 200

    def publish(self, content_topic: str, payload: bytes) -> bool:
        """Publish a raw payload to a Waku content topic.

        Args:
            content_topic: Waku content topic string.
            payload: Raw bytes to publish (will be base64-encoded).

        Returns:
            ``True`` if the publish succeeded.
        """
        encoded = base64.b64encode(payload).decode("ascii")
        now_ns = int(time.time() * 1e9)

        msg = {
            "payload": encoded,
            "contentTopic": content_topic,
            "timestamp": now_ns,
        }

        path = f"/relay/v1/messages/{self._encode_topic(PUBSUB_TOPIC)}"
        status, _ = self._request("POST", path, msg)
        return status == 200

    def poll(self, content_topic: Optional[str] = None) -> list[dict]:
        """Poll for raw messages from the relay subscription.

        Args:
            content_topic: If provided, only return messages matching this topic.

        Returns:
            List of dicts with keys ``content_topic``, ``payload`` (bytes),
            and ``timestamp``.
        """
        path = f"/relay/v1/messages/{self._encode_topic(PUBSUB_TOPIC)}"
        status, body = self._request("GET", path)

        if status != 200:
            return []

        try:
            messages = json.loads(body)
        except json.JSONDecodeError:
            return []

        results: list[dict] = []
        for msg in messages:
            ct = msg.get("contentTopic", "")
            if content_topic and ct != content_topic:
                continue
            try:
                payload = base64.b64decode(msg.get("payload", ""))
                results.append({
                    "content_topic": ct,
                    "payload": payload,
                    "timestamp": msg.get("timestamp", 0),
                })
            except Exception:
                continue

        return results

    def publish_json(self, content_topic: str, data: dict) -> bool:
        """Publish a JSON-serializable dict as a Waku message.

        Args:
            content_topic: Waku content topic string.
            data: Dict to serialize and publish.

        Returns:
            ``True`` if the publish succeeded.
        """
        payload = json.dumps(data).encode("utf-8")
        return self.publish(content_topic, payload)

    def poll_json(self, content_topic: Optional[str] = None) -> list[dict]:
        """Poll and parse JSON messages from the relay subscription.

        Silently skips messages that are not valid JSON.

        Args:
            content_topic: If provided, only return messages matching this topic.

        Returns:
            List of parsed JSON dicts. Each dict is augmented with
            ``_content_topic`` and ``_timestamp`` metadata keys.
        """
        messages = self.poll(content_topic)
        results: list[dict] = []
        for msg in messages:
            try:
                parsed = json.loads(msg["payload"])
                parsed["_content_topic"] = msg["content_topic"]
                parsed["_timestamp"] = msg["timestamp"]
                results.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue
        return results
