"""Pinned Unicode 17 data: verified inputs and a byte-reproducible generated table."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest

from okf_graph import unicode17_nfc
from tests.helpers import EXTRA_ROOT, FIXTURES


UCD = FIXTURES / "unicode17"


class TestUnicodeData(unittest.TestCase):
    def test_pinned_ucd_files_match_their_sha256sums(self) -> None:
        listed = {}
        for line in (UCD / "SHA256SUMS").read_text(encoding="ascii").splitlines():
            digest, name = line.split(None, 1)
            listed[name.strip()] = digest
        self.assertEqual(
            {
                "DerivedNormalizationProps.txt",
                "LICENSE.txt",
                "NormalizationTest.txt",
                "ReadMe.txt",
                "UnicodeData.txt",
            },
            set(listed),
        )
        for name, digest in sorted(listed.items()):
            with self.subTest(name=name):
                self.assertEqual(digest, hashlib.sha256((UCD / name).read_bytes()).hexdigest())

    def test_generator_reproduces_the_shipped_table_without_drift(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(EXTRA_ROOT / "tools" / "generate_unicode17_nfc.py"), "--check"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertFalse(report["drift"])
        self.assertEqual("17.0.0", report["unicode_version"])
        self.assertEqual(unicode17_nfc.TABLE_DIGEST, report["table_digest"])
        self.assertEqual(
            str(EXTRA_ROOT / "okf_graph" / "unicode17_data.py"), report["output"]
        )

    def test_runtime_tables_are_independent_of_the_host_unicodedata(self) -> None:
        self.assertEqual("17.0.0", unicode17_nfc.UNICODE_VERSION)
        self.assertTrue(unicode17_nfc.is_assigned17(0x10570))  # added in Unicode 14
        self.assertFalse(unicode17_nfc.is_assigned17(0x0378))
        self.assertFalse(unicode17_nfc.is_assigned17(0xD800))
        with self.assertRaises(unicode17_nfc.Unicode17Error):
            unicode17_nfc.normalize_nfc17("\ud800")


if __name__ == "__main__":
    unittest.main()
