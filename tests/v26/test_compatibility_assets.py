from __future__ import annotations

import pathlib
import unittest

from scripts.v26.compatibility import load_compatibility_metadata, resolve_route


ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "references/compatibility/v2.6/manifest.json"


class TestV26CompatibilityAssets(unittest.TestCase):
    def test_packaged_manifest_is_typed_and_preserves_unsupported_routes(self) -> None:
        metadata = load_compatibility_metadata(MANIFEST)
        self.assertEqual("V2.6", metadata["product_version"])
        route = resolve_route(metadata, "host.codex", "provider.deepseek/pro")
        self.assertEqual("unsupported_direct", route["connection_class"])
        self.assertEqual("blocked", route["verification_state"])
        self.assertEqual("provider.deepseek/pro", route["resolved_model"])


if __name__ == "__main__":
    unittest.main()
