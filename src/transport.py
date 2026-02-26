#!/usr/bin/env python3
"""
Claku — Waku Transport Layer
Handles publish/subscribe/poll via nwaku REST API.
"""

import json
import time
import base64
import urllib.parse
import urllib.request
from typing import Optional


PUBSUB_TOPIC = "/waku/2/rs/0/0"


class WakuTransport:
    """nwaku REST API transport for Claku messaging."""

    def __init__(self, waku_url: str = "http://localhost:8645"):
        self.waku_url = waku_url.rstrip("/")

    def _encode_topic(self, topic: str) -> str:
        return urllib.parse.quote(topic, safe="")

    def _request(self, method: str, path: str, data: Optional[dict] = None) -> tuple[int, str]:
        """Make HTTP request to nwaku REST API."""
        url = f"{self.waku_url}{path}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode("utf-8")
            except Exception:
                return e.code, str(e)
        except urllib.error.URLError as e:
            raise ConnectionError(f"Cannot reach nwaku at {self.waku_url}: {e.reason}")
        except OSError as e:
            raise ConnectionError(f"Network error connecting to {self.waku_url}: {e}")
        except Exception as e:
            return 0, str(e)

    def health(self) -> dict:
        """Check nwaku node health."""
        status, body = self._request("GET", "/health")
        if status == 200:
            return json.loads(body)
        return {"error": body, "status": status}

    def subscribe(self, pubsub_topic: str = PUBSUB_TOPIC) -> bool:
        """Subscribe to a pubsub topic."""
        status, body = self._request(
            "POST", "/relay/v1/subscriptions",
            [pubsub_topic]
        )
        return status == 200

    def publish(self, content_topic: str, payload: bytes) -> bool:
        """Publish a message to a content topic."""
        encoded = base64.b64encode(payload).decode("ascii")
        now_ns = int(time.time() * 1e9)

        msg = {
            "payload": encoded,
            "contentTopic": content_topic,
            "timestamp": now_ns,
        }

        path = f"/relay/v1/messages/{self._encode_topic(PUBSUB_TOPIC)}"
        status, body = self._request("POST", path, msg)
        return status == 200

    def poll(self, content_topic: Optional[str] = None) -> list[dict]:
        """Poll for messages. Optionally filter by content topic."""
        path = f"/relay/v1/messages/{self._encode_topic(PUBSUB_TOPIC)}"
        status, body = self._request("GET", path)

        if status != 200:
            return []

        try:
            messages = json.loads(body)
        except json.JSONDecodeError:
            return []

        results = []
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
        """Publish a JSON message."""
        payload = json.dumps(data).encode("utf-8")
        return self.publish(content_topic, payload)

    def poll_json(self, content_topic: Optional[str] = None) -> list[dict]:
        """Poll and parse JSON messages."""
        messages = self.poll(content_topic)
        results = []
        for msg in messages:
            try:
                parsed = json.loads(msg["payload"])
                parsed["_content_topic"] = msg["content_topic"]
                parsed["_timestamp"] = msg["timestamp"]
                results.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue
        return results
