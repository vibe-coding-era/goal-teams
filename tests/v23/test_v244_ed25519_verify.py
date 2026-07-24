from __future__ import annotations

import importlib.util
import unittest

from tests.v23.common import ROOT


PATH = ROOT / "scripts" / "release" / "ed25519_verify.py"
SPEC = importlib.util.spec_from_file_location("goal_teams_v244_ed25519", PATH)
assert SPEC is not None and SPEC.loader is not None
ed25519 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ed25519)


class V244Ed25519VerifyTests(unittest.TestCase):
    # RFC 8032 section 7.1, test vector 1 (empty message).
    PUBLIC_KEY = bytes.fromhex(
        "d75a980182b10ab7d54bfed3c964073a"
        "0ee172f3daa62325af021a68f707511a"
    )
    SIGNATURE = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a"
        "84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b"
    )

    def test_rfc8032_vector_is_accepted(self) -> None:
        self.assertTrue(
            ed25519.verify(self.PUBLIC_KEY, b"", self.SIGNATURE)
        )

    def test_payload_signature_and_key_tamper_are_rejected(self) -> None:
        cases = (
            (self.PUBLIC_KEY, b"x", self.SIGNATURE),
            (
                self.PUBLIC_KEY,
                b"",
                bytes([self.SIGNATURE[0] ^ 1]) + self.SIGNATURE[1:],
            ),
            (
                bytes([self.PUBLIC_KEY[0] ^ 1]) + self.PUBLIC_KEY[1:],
                b"",
                self.SIGNATURE,
            ),
            (self.PUBLIC_KEY, b"", self.SIGNATURE[:-1]),
            (self.PUBLIC_KEY[:-1], b"", self.SIGNATURE),
        )
        for public_key, message, signature in cases:
            with self.subTest(
                public_key=public_key.hex(),
                message=message,
                signature=signature.hex(),
            ):
                self.assertFalse(
                    ed25519.verify(public_key, message, signature)
                )

    def test_small_order_key_and_r_are_rejected(self) -> None:
        identity = bytes.fromhex("01" + "00" * 31)
        self.assertFalse(
            ed25519.verify(identity, b"", identity + b"\x00" * 32)
        )


if __name__ == "__main__":
    unittest.main()
