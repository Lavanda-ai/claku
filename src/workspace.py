#!/usr/bin/env python3
"""Workspace management for Claku projects."""
import json
import time
from pathlib import Path
from typing import Optional
from .identity import CLAKU_DIR

WORKSPACES_DIR = CLAKU_DIR / "workspaces"
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

def create_workspace(name: str, description: str, members: list[str]) -> dict:
    """Create new workspace."""
    ws_id = f"ws_{name.lower().replace(' ', '_')}"
    ws = {
        "id": ws_id,
        "name": name,
        "description": description,
        "members": members,
        "created": int(time.time()),
        "status": "active",
        "files": [],
        "issues": [],
        "decisions": []
    }
    ws_file = WORKSPACES_DIR / f"{ws_id}.json"
    ws_file.write_text(json.dumps(ws, indent=2))
    return ws

def list_workspaces() -> list[dict]:
    """List all workspaces."""
    return [json.loads(f.read_text()) for f in WORKSPACES_DIR.glob("*.json")]

def get_workspace(ws_id: str) -> Optional[dict]:
    """Get workspace by ID."""
    ws_file = WORKSPACES_DIR / f"{ws_id}.json"
    return json.loads(ws_file.read_text()) if ws_file.exists() else None

def add_issue(ws_id: str, title: str, description: str, assigned_to: str = None) -> dict:
    """Add issue to workspace."""
    ws = get_workspace(ws_id)
    if not ws:
        raise ValueError(f"Workspace {ws_id} not found")
    issue = {
        "id": f"issue_{len(ws['issues'])+1}",
        "title": title,
        "description": description,
        "status": "open",
        "assigned_to": assigned_to,
        "created": int(time.time())
    }
    ws["issues"].append(issue)
    ws_file = WORKSPACES_DIR / f"{ws_id}.json"
    ws_file.write_text(json.dumps(ws, indent=2))
    return issue

def add_decision(ws_id: str, title: str, description: str) -> dict:
    """Log decision in workspace."""
    ws = get_workspace(ws_id)
    if not ws:
        raise ValueError(f"Workspace {ws_id} not found")
    decision = {
        "id": f"decision_{len(ws['decisions'])+1}",
        "title": title,
        "description": description,
        "timestamp": int(time.time())
    }
    ws["decisions"].append(decision)
    ws_file = WORKSPACES_DIR / f"{ws_id}.json"
    ws_file.write_text(json.dumps(ws, indent=2))
    return decision
