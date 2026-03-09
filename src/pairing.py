#!/usr/bin/env python3
"""
Claku Human-Agent Pairing System.

Implements the 6-digit code pairing workflow for human-agent connections.
"""

import json
import time
import secrets
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from src.identity import CLAKU_DIR
    from src.transport import WakuTransport
    from src.crypto import sign_message, verify_signature, hex_to_bytes
except ImportError:
    # Handle relative imports when running as module
    from identity import CLAKU_DIR
    from transport import WakuTransport
    from crypto import sign_message, verify_signature, hex_to_bytes


PAIRING_DIR = CLAKU_DIR / "pairing"
PAIRING_DIR.mkdir(parents=True, exist_ok=True)

# Content topics for pairing messages
def PAIRING_REQUEST_TOPIC(agent_pubkey: str) -> str:
    """Content topic for pairing requests to a specific agent."""
    return f"/claku/0/pairing/request/{agent_pubkey}"


def PAIRING_RESPONSE_TOPIC(pairing_id: str) -> str:
    """Content topic for pairing responses."""
    return f"/claku/0/pairing/response/{pairing_id}"


class PairingManager:
    """Manages human-agent pairing with 6-digit codes."""
    
    def __init__(self, identity: Dict[str, Any], waku_url: str, auto_sharding: bool = False):
        self.identity = identity
        self.transport = WakuTransport(waku_url, auto_sharding=auto_sharding)
        self.pairing_file = PAIRING_DIR / "active_pairings.json"
        self.requests_file = PAIRING_DIR / "pending_requests.json"
        
    def _load_pairings(self) -> Dict[str, Any]:
        """Load active pairings from disk."""
        if not self.pairing_file.exists():
            return {}
        try:
            return json.loads(self.pairing_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
            
    def _save_pairings(self, pairings: Dict[str, Any]) -> None:
        """Save active pairings to disk."""
        self.pairing_file.write_text(json.dumps(pairings, indent=2))
        
    def _load_requests(self) -> Dict[str, Any]:
        """Load pending pairing requests from disk."""
        if not self.requests_file.exists():
            return {}
        try:
            return json.loads(self.requests_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
            
    def _save_requests(self, requests: Dict[str, Any]) -> None:
        """Save pending pairing requests to disk."""
        self.requests_file.write_text(json.dumps(requests, indent=2))
    
    def generate_pairing_code(self) -> str:
        """Generate a random 6-digit pairing code."""
        return f"{secrets.randbelow(1000000):06d}"
    
    def create_pairing_request(self, human_identifier: str) -> Dict[str, Any]:
        """Create a new pairing request for a human.
        
        Args:
            human_identifier: Human's identifier (email, phone, etc.)
            
        Returns:
            Dict containing pairing_id, code, and request details.
        """
        pairing_id = secrets.token_hex(16)
        code = self.generate_pairing_code()
        timestamp = int(time.time())
        
        request = {
            "pairing_id": pairing_id,
            "human_identifier": human_identifier,
            "code": code,
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "created_at": timestamp,
            "expires_at": timestamp + 300,  # 5 minutes
            "status": "pending"
        }
        
        # Save to pending requests
        requests = self._load_requests()
        requests[pairing_id] = request
        self._save_requests(requests)
        
        return request
    
    def send_pairing_request(self, human_identifier: str) -> Dict[str, Any]:
        """Send a pairing request to the network.
        
        Args:
            human_identifier: Human's identifier
            
        Returns:
            The pairing request dict with pairing_id and code.
        """
        request = self.create_pairing_request(human_identifier)
        
        # Publish the request to the agent's pairing topic
        msg = {
            "type": "pairing_request",
            "pairing_id": request["pairing_id"],
            "human_identifier": human_identifier,
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "created_at": request["created_at"],
            "expires_at": request["expires_at"],
            "ts": int(time.time())
        }
        
        # Sign the message
        sign_data = f"{request['pairing_id']}:{human_identifier}:{self.identity['pubkey']}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        msg["signature"] = sign_message(sign_data, ed_priv)
        
        topic = PAIRING_REQUEST_TOPIC(self.identity["pubkey"])
        ok = self.transport.publish_json(topic, msg)
        
        if not ok:
            raise ConnectionError("Failed to publish pairing request")
            
        return request
    
    def verify_pairing_code(self, pairing_id: str, code: str) -> bool:
        """Verify a pairing code for a given pairing ID.
        
        Args:
            pairing_id: The pairing ID to verify
            code: The 6-digit code provided by the human
            
        Returns:
            True if the code matches and hasn't expired
        """
        requests = self._load_requests()
        if pairing_id not in requests:
            return False
            
        request = requests[pairing_id]
        now = int(time.time())
        
        # Check if expired
        if now > request["expires_at"]:
            # Clean up expired request
            del requests[pairing_id]
            self._save_requests(requests)
            return False
            
        # Check code
        if request["code"] != code:
            return False
            
        return True
    
    def accept_pairing(self, pairing_id: str, human_pubkey: str = None) -> bool:
        """Accept a pairing request and establish the connection.
        
        Args:
            pairing_id: The pairing ID to accept
            human_pubkey: Optional human's public key for secure communication
            
        Returns:
            True if pairing was successful
        """
        requests = self._load_requests()
        if pairing_id not in requests:
            return False
            
        request = requests[pairing_id]
        now = int(time.time())
        
        # Check if expired
        if now > request["expires_at"]:
            del requests[pairing_id]
            self._save_requests(requests)
            return False
            
        # Create the pairing record
        pairing = {
            "pairing_id": pairing_id,
            "human_identifier": request["human_identifier"],
            "human_pubkey": human_pubkey,
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "paired_at": now,
            "status": "active"
        }
        
        # Save to active pairings
        pairings = self._load_pairings()
        pairings[pairing_id] = pairing
        self._save_pairings(pairings)
        
        # Remove from pending requests
        del requests[pairing_id]
        self._save_requests(requests)
        
        # Send acceptance response
        response_msg = {
            "type": "pairing_response",
            "pairing_id": pairing_id,
            "status": "accepted",
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "ts": now
        }
        
        # Sign the response
        sign_data = f"{pairing_id}:accepted:{self.identity['pubkey']}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        response_msg["signature"] = sign_message(sign_data, ed_priv)
        
        response_topic = PAIRING_RESPONSE_TOPIC(pairing_id)
        self.transport.publish_json(response_topic, response_msg)
        
        return True
    
    def refuse_pairing(self, pairing_id: str) -> bool:
        """Refuse a pairing request.
        
        Args:
            pairing_id: The pairing ID to refuse
            
        Returns:
            True if refusal was processed
        """
        requests = self._load_requests()
        if pairing_id not in requests:
            return False
            
        request = requests[pairing_id]
        
        # Remove from pending requests
        del requests[pairing_id]
        self._save_requests(requests)
        
        # Send refusal response
        response_msg = {
            "type": "pairing_response",
            "pairing_id": pairing_id,
            "status": "refused",
            "agent_pubkey": self.identity["pubkey"],
            "agent_name": self.identity["name"],
            "ts": int(time.time())
        }
        
        # Sign the response
        sign_data = f"{pairing_id}:refused:{self.identity['pubkey']}".encode("utf-8")
        ed_priv = hex_to_bytes(self.identity["secret"])
        response_msg["signature"] = sign_message(sign_data, ed_priv)
        
        response_topic = PAIRING_RESPONSE_TOPIC(pairing_id)
        self.transport.publish_json(response_topic, response_msg)
        
        return True
    
    def get_pending_requests(self) -> list:
        """Get all pending pairing requests."""
        requests = self._load_requests()
        now = int(time.time())
        valid_requests = []
        
        for req in requests.values():
            if now <= req["expires_at"]:
                valid_requests.append(req)
            else:
                # Clean up expired requests
                pass
                
        # Clean up expired requests
        clean_requests = {k: v for k, v in requests.items() if now <= v["expires_at"]}
        if len(clean_requests) != len(requests):
            self._save_requests(clean_requests)
            
        return valid_requests
    
    def get_active_pairings(self) -> list:
        """Get all active pairings."""
        pairings = self._load_pairings()
        return list(pairings.values())
    
    def poll_pairing_responses(self) -> list:
        """Poll for pairing responses addressed to this agent.
        
        Returns:
            List of pairing response messages.
        """
        # This would typically be called by the human side, but agents can also
        # monitor for responses if needed
        return []