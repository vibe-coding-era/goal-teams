"""Tests for tools/ed25519_verify.py (ported from tests/v23/test_v244_ed25519_verify.py)."""

from __future__ import annotations

import base64
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "tools" / "ed25519_verify.py"
SPEC = importlib.util.spec_from_file_location("goal_teams_ed25519_verify_tests", PATH)
assert SPEC is not None and SPEC.loader is not None
ed25519 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ed25519)

SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")

# RFC 8032 section 7.1, tests 1-3: (public key, message, signature).
VECTORS = (
    (
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
)


class Ed25519VerifyTests(unittest.TestCase):
    PUBLIC_KEY = bytes.fromhex(VECTORS[0][0])
    SIGNATURE = bytes.fromhex(VECTORS[0][2])

    def test_rfc8032_vectors_are_accepted(self) -> None:
        for public_key, message, signature in VECTORS:
            with self.subTest(public_key=public_key):
                self.assertTrue(
                    ed25519.verify(
                        bytes.fromhex(public_key), bytes.fromhex(message), bytes.fromhex(signature)
                    )
                )

    def test_payload_signature_and_key_tamper_are_rejected(self) -> None:
        cases = (
            (self.PUBLIC_KEY, b"x", self.SIGNATURE),
            (self.PUBLIC_KEY, b"", bytes([self.SIGNATURE[0] ^ 1]) + self.SIGNATURE[1:]),
            (bytes([self.PUBLIC_KEY[0] ^ 1]) + self.PUBLIC_KEY[1:], b"", self.SIGNATURE),
            (self.PUBLIC_KEY, b"", self.SIGNATURE[:-1]),
            (self.PUBLIC_KEY[:-1], b"", self.SIGNATURE),
            (bytes.fromhex(VECTORS[1][0]), b"", self.SIGNATURE),
        )
        for public_key, message, signature in cases:
            with self.subTest(public_key=public_key.hex(), message=message, signature=signature.hex()):
                self.assertFalse(ed25519.verify(public_key, message, signature))

    def test_small_order_key_and_r_are_rejected(self) -> None:
        identity = bytes.fromhex("01" + "00" * 31)
        self.assertFalse(ed25519.verify(identity, b"", identity + b"\x00" * 32))

    def test_non_canonical_s_is_rejected(self) -> None:
        s = int.from_bytes(self.SIGNATURE[32:], "little") + ed25519._L
        malleable = self.SIGNATURE[:32] + s.to_bytes(32, "little")
        self.assertFalse(ed25519.verify(self.PUBLIC_KEY, b"", malleable))


class LoadPublicKeyTests(unittest.TestCase):
    KEY = bytes.fromhex(VECTORS[1][0])
    # `openssl pkey -in key.pem -pubout` for the RFC 8032 test 2 key.
    OPENSSL_PEM = (
        b"-----BEGIN PUBLIC KEY-----\n"
        b"MCowBQYDK2VwAyEAPUAXw+hDiVqStwqnTRt+vJyYLM8uxJaMwM1V8Sr0Zgw=\n"
        b"-----END PUBLIC KEY-----\n"
    )

    def test_pem_subject_public_key_info(self) -> None:
        self.assertEqual(ed25519.load_public_key(self.OPENSSL_PEM), self.KEY)
        self.assertEqual(ed25519.load_public_key(self.OPENSSL_PEM.replace(b"\n", b"\r\n")), self.KEY)

    def test_der_and_hex(self) -> None:
        self.assertEqual(ed25519.load_public_key(SPKI_PREFIX + self.KEY), self.KEY)
        self.assertEqual(ed25519.load_public_key(self.KEY.hex().encode() + b"\n"), self.KEY)
        self.assertEqual(ed25519.load_public_key(self.KEY.hex().upper().encode()), self.KEY)

    def test_rejects_other_keys_and_garbage(self) -> None:
        pkcs8 = bytes.fromhex("302e020100300506032b657004220420") + b"\x01" * 32
        private_pem = (
            b"-----BEGIN PRIVATE KEY-----\n" + base64.b64encode(pkcs8) + b"\n-----END PRIVATE KEY-----\n"
        )
        x25519 = bytes.fromhex("302a300506032b656e032100") + self.KEY
        cases = {
            "private key": private_pem,
            "x25519 key": b"-----BEGIN PUBLIC KEY-----\n"
            + base64.b64encode(x25519)
            + b"\n-----END PUBLIC KEY-----\n",
            "two blocks": self.OPENSSL_PEM + self.OPENSSL_PEM,
            "bad base64": self.OPENSSL_PEM.replace(b"MCow", b"M!ow"),
            "truncated der": SPKI_PREFIX + self.KEY[:31],
            "short hex": self.KEY.hex()[:-1].encode(),
            "invalid point": ("ff" * 32).encode(),
            "empty": b"",
            "raw bytes": self.KEY,
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    ed25519.load_public_key(data)


if __name__ == "__main__":
    unittest.main()
