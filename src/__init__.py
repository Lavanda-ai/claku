"""Claku — Decentralized Agent Communication Platform"""
from .identity import get_or_create_identity, load_identity
from .transport import WakuTransport
from .node import ClakuNode

__version__ = "0.1.0"
__all__ = ["ClakuNode", "WakuTransport", "get_or_create_identity", "load_identity"]
