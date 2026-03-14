#!/usr/bin/env python3
"""
Agent configuration management.
Controls how the agent interacts with others.
"""

import json
from pathlib import Path

try:
    from src.identity import CLAKU_DIR
except ImportError:
    CLAKU_DIR = Path.home() / ".claku"

AGENT_CONFIG_FILE = CLAKU_DIR / "agent_config.json"

DEFAULT_CONFIG = {
    "auto_accept_connections": False,
    "auto_join_circles": False,
    "auto_vote_proposals": False,
    "response_mode": "passive",  # silent, passive, active
    "trust_threshold": 3.0,  # 0-5
    "rate_limits": {
        "messages_per_hour": 10,
        "proposals_per_day": 5,
        "votes_per_day": 20
    },
    "allowed_actions": [
        "announce",
        "discover",
        "send_channel",
        "send_dm",
        "circle_create",
        "circle_join",
        "circle_propose",
        "circle_vote"
    ],
    "block_list": [],
    "notifications": {
        "new_proposals": True,
        "new_dms": True,
        "connection_requests": True,
        "votes": False
    }
}

def load_agent_config() -> dict:
    """Load agent configuration."""
    if not AGENT_CONFIG_FILE.exists():
        save_agent_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    
    with open(AGENT_CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_agent_config(config: dict) -> None:
    """Save agent configuration."""
    CLAKU_DIR.mkdir(parents=True, exist_ok=True)
    with open(AGENT_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def update_agent_config(key: str, value) -> None:
    """Update a single config value."""
    config = load_agent_config()
    
    # Handle nested keys like "rate_limits.messages_per_hour"
    if '.' in key:
        parts = key.split('.')
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    else:
        config[key] = value
    
    save_agent_config(config)

def get_agent_config(key: str = None):
    """Get config value or entire config."""
    config = load_agent_config()
    if key is None:
        return config
    
    # Handle nested keys
    if '.' in key:
        parts = key.split('.')
        current = config
        for part in parts:
            current = current.get(part, {})
        return current
    
    return config.get(key)
