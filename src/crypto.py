#!/usr/bin/env python3
"""
Claku — Cryptography Module.

X25519 ECDH key exchange + ChaCha20-Poly1305 AEAD encryption for DMs.
Ed25519 signing for channel message authentication.
"""

import os
import base64
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)


def generate_x25519_keypair() -> Tuple[bytes, bytes]:
    """Generate X25519 keypair. Returns (private_bytes, public_bytes)."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def generate_ed25519_keypair() -> Tuple[bytes, bytes]:
    """Generate Ed25519 signing keypair. Returns (private_bytes, public_bytes)."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def ecdh_shared_secret(my_private: bytes, their_public: bytes) -> bytes:
    """Derive shared secret via X25519 ECDH."""
    priv = X25519PrivateKey.from_private_bytes(my_private)
    pub = X25519PublicKey.from_public_bytes(their_public)
    return priv.exchange(pub)


def encrypt(plaintext: bytes, shared_secret: bytes) -> bytes:
    """Encrypt with ChaCha20-Poly1305. Returns nonce(12) + ciphertext."""
    nonce = os.urandom(12)
    aead = ChaCha20Poly1305(shared_secret)
    ct = aead.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt(data: bytes, shared_secret: bytes) -> bytes:
    """Decrypt ChaCha20-Poly1305. Input: nonce(12) + ciphertext."""
    if len(data) < 13:
        raise ValueError("Ciphertext too short")
    nonce = data[:12]
    ct = data[12:]
    aead = ChaCha20Poly1305(shared_secret)
    return aead.decrypt(nonce, ct, None)


def encrypt_for_recipient(plaintext: bytes, my_x25519_private: bytes,
                          their_x25519_public: bytes) -> str:
    """Encrypt a message for a specific recipient. Returns base64-encoded blob."""
    shared = ecdh_shared_secret(my_x25519_private, their_x25519_public)
    encrypted = encrypt(plaintext, shared)
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_from_sender(encrypted_b64: str, my_x25519_private: bytes,
                        their_x25519_public: bytes) -> bytes:
    """Decrypt a message from a specific sender. Input: base64-encoded blob."""
    data = base64.b64decode(encrypted_b64)
    shared = ecdh_shared_secret(my_x25519_private, their_x25519_public)
    return decrypt(data, shared)


def sign_message(message: bytes, ed25519_private: bytes) -> str:
    """Sign a message with Ed25519. Returns base64-encoded signature."""
    priv = Ed25519PrivateKey.from_private_bytes(ed25519_private)
    sig = priv.sign(message)
    return base64.b64encode(sig).decode("ascii")


def verify_signature(message: bytes, signature_b64: str,
                     ed25519_public: bytes) -> bool:
    """Verify an Ed25519 signature. Returns True if valid."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(ed25519_public)
        sig = base64.b64decode(signature_b64)
        pub.verify(sig, message)
        return True
    except Exception:
        return False


def bytes_to_hex(b: bytes) -> str:
    return b.hex()


def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h)
