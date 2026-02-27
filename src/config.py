#!/usr/bin/env python3
"""
Claku — Configuration Module.

Manages persistent agent configuration stored in ~/.claku/config.json.
Supports environment variable overrides.
"""

import os
import json
from typing import Any, Optional

CONFIG_DIR = os.path.expanduser("~/.claku")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "waku_url": "http://212.227.95.210:8645",
    "auto_sharding": True,
    "cluster_id": 1,
    "default_channel": "#general",
    "dashboard_log": os.path.join(CONFIG_DIR, "dashboard.jsonl"),
}

# Environment variable mappings: ENV_VAR -> config_key
ENV_MAP = {
    "CLAKU_WAKU_URL": "waku_url",
    "CLAKU_AUTO_SHARDING": "auto_sharding",
    "CLAKU_CLUSTER_ID": "cluster_id",
    "CLAKU_DEFAULT_CHANNEL": "default_channel",
}

# Keys that should be parsed as booleans from env
BOOL_KEYS = {"auto_sharding"}

# Keys that should be parsed as integers from env
INT_KEYS = {"cluster_id"}


def _parse_env_value(key: str, value: str) -> Any:
    """Parse an environment variable string into the correct type."""
    if key in BOOL_KEYS:
        return value.lower() in ("1", "true", "yes", "on")
    if key in INT_KEYS:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def load_config() -> dict:
    """Load configuration with priority: env vars > config file > defaults."""
    config = dict(DEFAULTS)

    # Layer 1: config file
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                file_config = json.load(f)
            config.update(file_config)
        except (json.JSONDecodeError, OSError):
            pass

    # Layer 2: environment variables (highest priority)
    for env_var, config_key in ENV_MAP.items():
        val = os.environ.get(env_var)
        if val is not None:
            config[config_key] = _parse_env_value(config_key, val)

    return config


def save_config(config: dict) -> None:
    """Save configuration to ~/.claku/config.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, default: Any = None) -> Any:
    """Get a single config value."""
    return load_config().get(key, default)


def set_value(key: str, value: Any) -> None:
    """Set a single config value and persist."""
    config = load_config()
    config[key] = value
    save_config(config)
