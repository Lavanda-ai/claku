"""Claku — Agent Operating Layer for Logos Network."""

from .identity import get_or_create_identity, load_identity
from .transport import WakuTransport
from .node import ClakuNode
from .config import load_config, save_config
from .crypto import (
    encrypt_for_recipient, decrypt_from_sender,
    sign_message, verify_signature,
)

__version__ = "0.5.0"
__all__ = [
    "ClakuNode",
    "WakuTransport",
    "get_or_create_identity",
    "load_identity",
    "load_config",
    "save_config",
    "encrypt_for_recipient",
    "decrypt_from_sender",
    "sign_message",
    "verify_signature",
]
