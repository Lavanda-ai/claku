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

    Supports two modes:
    - **static** (cluster 0): uses ``/relay/v1/`` with explicit pubsub topics
    - **auto** (cluster 1+): uses ``/relay/v1/auto/`` with content-topic-based sharding
    """

    def __init__(self, waku_url: str = "http://localhost:8645", auto_sharding: bool = False) -> None:
        self.waku_url: str = waku_url.rstrip("/")
        self.auto_sharding: bool = auto_sharding

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

    def subscribe(self, topic: str = PUBSUB_TOPIC) -> bool:
        """Subscribe to a topic for relay messages.

        In auto-sharding mode, *topic* is treated as a content topic and
        subscribed via ``/relay/v1/auto/subscriptions``.  In static mode
        it is a pubsub topic subscribed via ``/relay/v1/subscriptions``.

        Returns:
            ``True`` if the subscription succeeded.
        """
        if self.auto_sharding:
            path = "/relay/v1/auto/subscriptions"
        else:
            path = "/relay/v1/subscriptions"
        status, _ = self._request("POST", path, [topic])
        return status == 200

    def publish(self, content_topic: str, payload: bytes) -> bool:
        """Publish a raw payload to a Waku content topic.

        In auto-sharding mode, publishes via ``/relay/v1/auto/messages/``.
        In static mode, publishes via ``/relay/v1/messages/{pubsub_topic}``.

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

        if self.auto_sharding:
            path = "/relay/v1/auto/messages"
        else:
            path = f"/relay/v1/messages/{self._encode_topic(PUBSUB_TOPIC)}"
        status, _ = self._request("POST", path, msg)
        return status == 200

    def poll(self, content_topic: Optional[str] = None) -> list[dict]:
        """Poll for raw messages from the relay subscription.

        In auto-sharding mode, polls ``/relay/v1/auto/messages/{content_topic}``.
        In static mode, polls ``/relay/v1/messages/{pubsub_topic}`` and filters
        by content topic client-side.

        Args:
            content_topic: Content topic to poll. Required in auto-sharding mode.

        Returns:
            List of dicts with keys ``content_topic``, ``payload`` (bytes),
            and ``timestamp``.
        """
        if self.auto_sharding:
            if not content_topic:
                return []
            path = f"/relay/v1/auto/messages/{self._encode_topic(content_topic)}"
        else:
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

    def store_query(
        self,
        content_topics: Optional[list[str]] = None,
        page_size: int = 20,
        cursor: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> dict:
        """Query historical messages from the Waku Store protocol (v3).

        Args:
            content_topics: Filter by content topics.
            page_size: Max messages per page (default 20).
            cursor: Pagination cursor from a previous query.
            start_time: Start time filter (nanoseconds since epoch).
            end_time: End time filter (nanoseconds since epoch).

        Returns:
            Dict with ``messages`` (list), ``paginationCursor`` (str or None),
            and ``statusCode``.
        """
        params = [f"pageSize={page_size}"]
        if content_topics:
            for ct in content_topics:
                params.append(f"contentTopics={urllib.parse.quote(ct, safe='')}")
        if cursor:
            params.append(f"cursor={cursor}")
        if start_time:
            params.append(f"startTime={start_time}")
        if end_time:
            params.append(f"endTime={end_time}")

        query = "&".join(params)
        path = f"/store/v3/messages?{query}"
        status, body = self._request("GET", path)

        if status != 200:
            return {"messages": [], "statusCode": status, "error": body}

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {"messages": [], "statusCode": status, "error": "Invalid JSON"}

        # Decode payloads
        messages = []
        for msg in data.get("messages", []):
            entry = {
                "message_hash": msg.get("messageHash", ""),
            }
            # Full message may include payload if includeData is set
            if "payload" in msg:
                try:
                    entry["payload"] = base64.b64decode(msg["payload"])
                except Exception:
                    entry["payload"] = b""
            if "contentTopic" in msg:
                entry["content_topic"] = msg["contentTopic"]
            if "timestamp" in msg:
                entry["timestamp"] = msg["timestamp"]
            messages.append(entry)

        return {
            "messages": messages,
            "paginationCursor": data.get("paginationCursor"),
            "statusCode": data.get("statusCode", status),
        }

    def store_query_json(
        self,
        content_topics: Optional[list[str]] = None,
        page_size: int = 20,
    ) -> list[dict]:
        """Query and parse JSON messages from the Waku Store.

        Convenience wrapper that decodes JSON payloads and paginates
        through all available results.

        Args:
            content_topics: Filter by content topics.
            page_size: Messages per page.

        Returns:
            List of parsed JSON dicts.
        """
        results = []
        cursor = None
        while True:
            resp = self.store_query(content_topics, page_size, cursor)
            for msg in resp.get("messages", []):
                payload = msg.get("payload", b"")
                if payload:
                    try:
                        parsed = json.loads(payload)
                        parsed["_message_hash"] = msg.get("message_hash", "")
                        parsed["_content_topic"] = msg.get("content_topic", "")
                        parsed["_timestamp"] = msg.get("timestamp", 0)
                        results.append(parsed)
                    except (json.JSONDecodeError, KeyError):
                        continue
            cursor = resp.get("paginationCursor")
            if not cursor or not resp.get("messages"):
                break
        return results
