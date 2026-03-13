#!/usr/bin/env python3
"""Workspace management for Claku projects."""
import json
import time
import uuid
from pathlib import Path
from typing import Optional
from .identity import CLAKU_DIR
from .transport import WakuTransport

WORKSPACES_DIR = CLAKU_DIR / "workspaces"
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

def WORKSPACE_TOPIC(ws_id: str) -> str:
    """Content topic for workspace messages."""
    return f"/claku/1/workspace/{ws_id}/proto"

class WorkspaceManager:
    """Manages project workspaces for agent collaboration."""
    
    def __init__(self, agent_identity: dict, transport: WakuTransport):
        self.identity = agent_identity
        self.transport = transport
        self.workspaces = self._load_local_workspaces()
    
    def _load_local_workspaces(self) -> dict:
        """Load workspaces from local storage."""
        workspaces = {}
        for f in WORKSPACES_DIR.glob("*.json"):
            try:
                ws = json.loads(f.read_text())
                workspaces[ws["id"]] = ws
            except:
                pass
        return workspaces
    
    def _save_workspace(self, ws: dict) -> None:
        """Save workspace to local storage."""
        ws_file = WORKSPACES_DIR / f"{ws['id']}.json"
        ws_file.write_text(json.dumps(ws, indent=2))
        self.workspaces[ws["id"]] = ws
    
    def create_workspace(self, name: str, description: str = "") -> dict:
        """Create new workspace and announce it."""
        ws_id = f"ws_{name.lower().replace(' ', '_').replace('-', '_')}"
        ws = {
            "id": ws_id,
            "name": name,
            "description": description,
            "creator": self.identity["name"],
            "creator_pubkey": self.identity["pubkey"],
            "members": [self.identity["pubkey"]],
            "created": int(time.time()),
            "status": "active",
            "issues": [],
            "decisions": []
        }
        
        # Save locally
        self._save_workspace(ws)
        
        # Announce to network
        announcement = {
            "type": "workspace_create",
            "workspace_id": ws_id,
            "name": name,
            "description": description,
            "creator": self.identity["name"],
            "creator_pubkey": self.identity["pubkey"],
            "ts": int(time.time()),
            "msg_id": str(uuid.uuid4())
        }
        
        self.transport.publish_json(WORKSPACE_TOPIC(ws_id), announcement)
        return ws
    
    def join_workspace(self, ws_id: str) -> bool:
        """Join an existing workspace."""
        # Check if workspace exists locally
        if ws_id not in self.workspaces:
            # Try to fetch from Waku
            self.poll_workspace(ws_id)
        
        if ws_id not in self.workspaces:
            return False
        
        ws = self.workspaces[ws_id]
        if self.identity["pubkey"] not in ws["members"]:
            ws["members"].append(self.identity["pubkey"])
            self._save_workspace(ws)
        
        # Announce join
        join_msg = {
            "type": "workspace_join",
            "workspace_id": ws_id,
            "agent_name": self.identity["name"],
            "agent_pubkey": self.identity["pubkey"],
            "ts": int(time.time()),
            "msg_id": str(uuid.uuid4())
        }
        
        self.transport.publish_json(WORKSPACE_TOPIC(ws_id), join_msg)
        return True
    
    def add_issue(self, ws_id: str, title: str, description: str = "", assigned_to: str = None) -> dict:
        """Add issue to workspace."""
        if ws_id not in self.workspaces:
            raise ValueError(f"Workspace {ws_id} not found")
        
        ws = self.workspaces[ws_id]
        issue = {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "status": "open",
            "assigned_to": assigned_to,
            "created_by": self.identity["name"],
            "created": int(time.time())
        }
        
        ws["issues"].append(issue)
        self._save_workspace(ws)
        
        # Publish to workspace topic
        issue_msg = {
            "type": "workspace_issue",
            "workspace_id": ws_id,
            "issue": issue,
            "ts": int(time.time()),
            "msg_id": str(uuid.uuid4())
        }
        
        self.transport.publish_json(WORKSPACE_TOPIC(ws_id), issue_msg)
        return issue
    
    def add_decision(self, ws_id: str, title: str, description: str = "") -> dict:
        """Log decision in workspace."""
        if ws_id not in self.workspaces:
            raise ValueError(f"Workspace {ws_id} not found")
        
        ws = self.workspaces[ws_id]
        decision = {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "decided_by": self.identity["name"],
            "timestamp": int(time.time())
        }
        
        ws["decisions"].append(decision)
        self._save_workspace(ws)
        
        # Publish to workspace topic
        decision_msg = {
            "type": "workspace_decision",
            "workspace_id": ws_id,
            "decision": decision,
            "ts": int(time.time()),
            "msg_id": str(uuid.uuid4())
        }
        
        self.transport.publish_json(WORKSPACE_TOPIC(ws_id), decision_msg)
        return decision
    
    def poll_workspace(self, ws_id: str) -> list[dict]:
        """Poll workspace topic for updates."""
        topic = WORKSPACE_TOPIC(ws_id)
        messages = self.transport.store_query_json([topic], page_size=50)
        
        for msg in messages:
            msg_type = msg.get("type")
            
            if msg_type == "workspace_create":
                # Create workspace locally if we don't have it
                if ws_id not in self.workspaces:
                    ws = {
                        "id": ws_id,
                        "name": msg.get("name"),
                        "description": msg.get("description", ""),
                        "creator": msg.get("creator"),
                        "creator_pubkey": msg.get("creator_pubkey"),
                        "members": [msg.get("creator_pubkey")],
                        "created": msg.get("ts"),
                        "status": "active",
                        "issues": [],
                        "decisions": []
                    }
                    self._save_workspace(ws)
            
            elif msg_type == "workspace_join":
                if ws_id in self.workspaces:
                    ws = self.workspaces[ws_id]
                    agent_pubkey = msg.get("agent_pubkey")
                    if agent_pubkey and agent_pubkey not in ws["members"]:
                        ws["members"].append(agent_pubkey)
                        self._save_workspace(ws)
            
            elif msg_type == "workspace_issue":
                if ws_id in self.workspaces:
                    ws = self.workspaces[ws_id]
                    issue = msg.get("issue")
                    if issue and not any(i["id"] == issue["id"] for i in ws["issues"]):
                        ws["issues"].append(issue)
                        self._save_workspace(ws)
            
            elif msg_type == "workspace_decision":
                if ws_id in self.workspaces:
                    ws = self.workspaces[ws_id]
                    decision = msg.get("decision")
                    if decision and not any(d["id"] == decision["id"] for d in ws["decisions"]):
                        ws["decisions"].append(decision)
                        self._save_workspace(ws)
        
        return messages
    
    def list_workspaces(self) -> list[dict]:
        """List all known workspaces."""
        return list(self.workspaces.values())
    
    def get_workspace(self, ws_id: str) -> Optional[dict]:
        """Get workspace by ID."""
        return self.workspaces.get(ws_id)
