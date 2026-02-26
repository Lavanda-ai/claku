#!/usr/bin/env python3
"""Tests for Claku crypto module — Ed25519 signing + X25519/ChaCha20 encryption."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from src.crypto import (
    generate_x25519_keypair, generate_ed25519_keypair,
    ecdh_shared_secret, encrypt, decrypt,
    encrypt_for_recipient, decrypt_from_sender,
    sign_message, verify_signature,
    bytes_to_hex, hex_to_bytes,
)


class TestX25519(unittest.TestCase):
    def test_keypair_generation(self):
        priv, pub = generate_x25519_keypair()
        self.assertEqual(len(priv), 32)
        self.assertEqual(len(pub), 32)
        self.assertNotEqual(priv, pub)

    def test_keypair_uniqueness(self):
        _, pub1 = generate_x25519_keypair()
        _, pub2 = generate_x25519_keypair()
        self.assertNotEqual(pub1, pub2)

    def test_ecdh_shared_secret_symmetric(self):
        priv_a, pub_a = generate_x25519_keypair()
        priv_b, pub_b = generate_x25519_keypair()
        secret_ab = ecdh_shared_secret(priv_a, pub_b)
        secret_ba = ecdh_shared_secret(priv_b, pub_a)
        self.assertEqual(secret_ab, secret_ba)
        self.assertEqual(len(secret_ab), 32)


class TestChaCha20Poly1305(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        secret = os.urandom(32)
        plaintext = b"Hello Claku!"
        ct = encrypt(plaintext, secret)
        result = decrypt(ct, secret)
        self.assertEqual(result, plaintext)

    def test_nonce_prepended(self):
        secret = os.urandom(32)
        ct = encrypt(b"test", secret)
        # nonce(12) + ciphertext(4 + 16 tag) = at least 32 bytes
        self.assertGreater(len(ct), 12)

    def test_different_nonces(self):
        secret = os.urandom(32)
        ct1 = encrypt(b"same", secret)
        ct2 = encrypt(b"same", secret)
        self.assertNotEqual(ct1, ct2)  # different nonces

    def test_wrong_key_fails(self):
        secret1 = os.urandom(32)
        secret2 = os.urandom(32)
        ct = encrypt(b"secret data", secret1)
        with self.assertRaises(Exception):
            decrypt(ct, secret2)

    def test_tampered_ciphertext_fails(self):
        secret = os.urandom(32)
        ct = bytearray(encrypt(b"important", secret))
        ct[-1] ^= 0xFF  # flip last byte
        with self.assertRaises(Exception):
            decrypt(bytes(ct), secret)

    def test_too_short_ciphertext(self):
        with self.assertRaises(ValueError):
            decrypt(b"short", os.urandom(32))


class TestE2EEncryption(unittest.TestCase):
    def test_encrypt_decrypt_for_recipient(self):
        priv_a, pub_a = generate_x25519_keypair()
        priv_b, pub_b = generate_x25519_keypair()
        msg = b"Secret message between agents"
        encrypted = encrypt_for_recipient(msg, priv_a, pub_b)
        decrypted = decrypt_from_sender(encrypted, priv_b, pub_a)
        self.assertEqual(decrypted, msg)

    def test_wrong_recipient_fails(self):
        priv_a, pub_a = generate_x25519_keypair()
        _, pub_b = generate_x25519_keypair()
        priv_c, _ = generate_x25519_keypair()
        encrypted = encrypt_for_recipient(b"for B only", priv_a, pub_b)
        with self.assertRaises(Exception):
            decrypt_from_sender(encrypted, priv_c, pub_a)

    def test_empty_message(self):
        priv_a, pub_a = generate_x25519_keypair()
        priv_b, pub_b = generate_x25519_keypair()
        encrypted = encrypt_for_recipient(b"", priv_a, pub_b)
        decrypted = decrypt_from_sender(encrypted, priv_b, pub_a)
        self.assertEqual(decrypted, b"")

    def test_large_message(self):
        priv_a, pub_a = generate_x25519_keypair()
        priv_b, pub_b = generate_x25519_keypair()
        msg = os.urandom(10000)
        encrypted = encrypt_for_recipient(msg, priv_a, pub_b)
        decrypted = decrypt_from_sender(encrypted, priv_b, pub_a)
        self.assertEqual(decrypted, msg)


class TestEd25519Signing(unittest.TestCase):
    def test_sign_verify(self):
        priv, pub = generate_ed25519_keypair()
        msg = b"Claku protocol message"
        sig = sign_message(msg, priv)
        self.assertTrue(verify_signature(msg, sig, pub))

    def test_wrong_key_rejects(self):
        priv, _ = generate_ed25519_keypair()
        _, pub2 = generate_ed25519_keypair()
        sig = sign_message(b"signed by A", priv)
        self.assertFalse(verify_signature(b"signed by A", sig, pub2))

    def test_tampered_message_rejects(self):
        priv, pub = generate_ed25519_keypair()
        sig = sign_message(b"original", priv)
        self.assertFalse(verify_signature(b"tampered", sig, pub))

    def test_empty_message(self):
        priv, pub = generate_ed25519_keypair()
        sig = sign_message(b"", priv)
        self.assertTrue(verify_signature(b"", sig, pub))

    def test_keypair_sizes(self):
        priv, pub = generate_ed25519_keypair()
        self.assertEqual(len(priv), 32)
        self.assertEqual(len(pub), 32)


class TestHexUtils(unittest.TestCase):
    def test_roundtrip(self):
        data = os.urandom(32)
        self.assertEqual(hex_to_bytes(bytes_to_hex(data)), data)

    def test_known_value(self):
        self.assertEqual(bytes_to_hex(b"\xde\xad"), "dead")
        self.assertEqual(hex_to_bytes("dead"), b"\xde\xad")


if __name__ == "__main__":
    unittest.main()
