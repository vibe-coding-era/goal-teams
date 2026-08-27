from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV262PublishedProjectionBoundaries(unittest.TestCase):
    def test_assurance_limits_and_immutable_asset_boundary_remain_explicit(self) -> None:
        manifest = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "reproducibility": "not_verified_by_v250_policy",
                "s2_security_checks": "not_run_by_v250_policy",
                "fresh_runtime_transition": "I1_correlated_not_external_independence",
                "kg_parser_scope": (
                    "controlled_markdown_lexical_subset_not_commonmark_gfm_conformance"
                ),
                "kg_digest_scope": "graph_input_manifest_not_rdf_dataset",
                "kg_isolated_entity_detector": "not_implemented",
                "kg_compile_resource_budget": "not_implemented",
                "kg_trace_truncated_match_count": (
                    "discovered_lower_bound_not_total_reachable_edges"
                ),
            },
            manifest["assurance_limits"],
        )
        readme = (ROOT / "release/current/README.md").read_text(encoding="utf-8")
        self.assertIn("post-release `main` projection", readme)
        self.assertIn(
            f"immutable {manifest['product_version']} assets retain the candidate-time",
            readme,
        )
        self.assertIn("are not rewritten after publication", readme)


if __name__ == "__main__":
    unittest.main()
