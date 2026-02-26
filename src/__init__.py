"""Claku — Decentralized Agent Communication Platform over Waku."""

from .identity import get_or_create_identity, load_identity
from .transport import WakuTransport
from .node import ClakuNode

__version__ = "0.2.0"
__all__ = ["ClakuNode", "WakuTransport", "get_or_create_identity", "load_identity"]
