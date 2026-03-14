#!/usr/bin/env python3
"""
Approval queue for high-risk agent actions.
Human must approve before agent executes.
"""

import json
import time
import uuid
from pathlib import Path

try:
    from src.identity import CLAKU_DIR
except ImportError:
    CLAKU_DIR = Path.home() / ".claku"

APPROVALS_FILE = CLAKU_DIR / "approvals.json"

def load_approvals() -> dict:
    """Load pending approvals."""
    if not APPROVALS_FILE.exists():
        return {}
    
    with open(APPROVALS_FILE, 'r') as f:
        return json.load(f)

def save_approvals(approvals: dict) -> None:
    """Save approvals."""
    CLAKU_DIR.mkdir(parents=True, exist_ok=True)
    with open(APPROVALS_FILE, 'w') as f:
        json.dump(approvals, f, indent=2)

def request_approval(action_type: str, data: dict) -> str:
    """Request human approval for an action."""
    approval_id = str(uuid.uuid4())
    
    approvals = load_approvals()
    approvals[approval_id] = {
        "id": approval_id,
        "type": action_type,
        "data": data,
        "status": "pending",
        "requested_at": int(time.time()),
        "expires_at": int(time.time()) + 86400  # 24 hours
    }
    save_approvals(approvals)
    
    return approval_id

def get_pending_approvals() -> list:
    """Get all pending approvals."""
    approvals = load_approvals()
    now = int(time.time())
    
    pending = []
    for approval_id, approval in list(approvals.items()):
        if approval["status"] == "pending":
            # Check if expired
            if now > approval["expires_at"]:
                approval["status"] = "expired"
                save_approvals(approvals)
            else:
                pending.append(approval)
    
    return pending

def approve_action(approval_id: str) -> bool:
    """Approve an action."""
    approvals = load_approvals()
    if approval_id not in approvals:
        return False
    
    approvals[approval_id]["status"] = "approved"
    approvals[approval_id]["approved_at"] = int(time.time())
    save_approvals(approvals)
    return True

def deny_action(approval_id: str) -> bool:
    """Deny an action."""
    approvals = load_approvals()
    if approval_id not in approvals:
        return False
    
    approvals[approval_id]["status"] = "denied"
    approvals[approval_id]["denied_at"] = int(time.time())
    save_approvals(approvals)
    return True

def get_approval_status(approval_id: str) -> str:
    """Get status of an approval request."""
    approvals = load_approvals()
    if approval_id not in approvals:
        return "not_found"
    
    return approvals[approval_id]["status"]
