from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "7" * 64
PROFILE_SHA256 = "8" * 64
HTML_BLANK_TERMINATED_STARTS = (
    "</div>",
    "<div></div>",
    "<hr>",
    "<div />",
)


def _load(root: Path):
    return kg.load_current_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


def _frontmatter(
    *, knowledge_id: str, document_type: str = "Knowledge Note"
) -> str:
    return f"""---
type: {document_type}
title: HTML block boundary adversarial fixture
description: Complete HTML block starts cannot authorize graph facts.
timestamp: 2026-08-08T02:00:00+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: product.current
knowledge_id: {knowledge_id}
revision: "1"
owner: parser-owner
lifecycle: current
modality: note
epistemic_state: documented
sensitivity: internal
---
"""


def _member_table(knowledge_id: str, path: str) -> str:
    return "\n".join(
        (
            "| member_ref | path | member_kind | lifecycle |",
            "| --- | --- | --- | --- |",
            f"| `product.current:{knowledge_id}@1` | [Member]({path}) | "
            "`Knowledge Note` | `current` |",
        )
    )


def _map_with_body(body: str) -> str:
    return (
        _frontmatter(knowledge_id="MAP-HTML-BLOCK", document_type="Knowledge Map")
        + "\n# HTML block map\n\n"
        + body
        + "\n"
    )


def _document(knowledge_id: str, body: str) -> str:
    return _frontmatter(knowledge_id=knowledge_id) + "\n" + body + "\n"


def _active_map(*items: tuple[str, str]) -> str:
    rows = [
        "## Members",
        "",
        "| member_ref | path | member_kind | lifecycle |",
        "| --- | --- | --- | --- |",
    ]
    rows.extend(
        f"| `product.current:{knowledge_id}@1` | [Member]({path}) | "
        "`Knowledge Note` | `current` |"
        for knowledge_id, path in items
    )
    return _map_with_body("\n".join(rows))


def _relation_table(relation_id: str, predicate: str) -> str:
    return "\n".join(
        (
            "#### Relations",
            "| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            f"| `{relation_id}` | `{predicate}` | "
            "`product.current:SOURCE@1#CLM-SOURCE` | "
            "[Self](source.md#CLM-SOURCE) | `asserted` | `boundary` | "
            "[Self](source.md#CLM-SOURCE) |",
        )
    )


class TestV262KnowledgeGraphAdversarialRound7(unittest.TestCase):
    def test_complete_html_block_starts_mask_members_until_blank_line(self) -> None:
        for ordinal, html_start in enumerate(
            HTML_BLANK_TERMINATED_STARTS, start=1
        ):
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="kg262-html-members-"
            ) as tmp:
                root = Path(tmp)
                hidden_id = f"HIDDEN-{ordinal}"
                body = "\n".join(
                    (
                        html_start,
                        "## Members",
                        _member_table(hidden_id, "hidden.md"),
                        "",
                        "## Members",
                        "",
                        _member_table("ACTIVE", "active.md"),
                    )
                )
                (root / "knowledge-map.md").write_text(
                    _map_with_body(body), encoding="utf-8"
                )
                (root / "hidden.md").write_text(
                    _document(hidden_id, "### CLM-HIDDEN\n\nHidden."),
                    encoding="utf-8",
                )
                (root / "active.md").write_text(
                    _document("ACTIVE", "### CLM-ACTIVE\n\nActive."),
                    encoding="utf-8",
                )

                graph = _load(root)
                self.assertEqual(
                    [],
                    graph.resolve(
                        f"product.current:{hidden_id}@1#CLM-HIDDEN"
                    )["results"],
                )
                self.assertEqual(
                    1,
                    len(
                        graph.resolve(
                            "product.current:ACTIVE@1#CLM-ACTIVE"
                        )["results"]
                    ),
                )

    def test_complete_html_block_starts_mask_claims_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="kg262-html-claims-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                body = "\n".join(
                    (
                        "# Source",
                        "",
                        html_start,
                        "### CLM-HIDDEN",
                        "Hidden sample syntax.",
                        "",
                        "### CLM-ACTIVE",
                        "",
                        "Active claim.",
                    )
                )
                (root / "source.md").write_text(
                    _document("SOURCE", body), encoding="utf-8"
                )

                graph = _load(root)
                self.assertEqual(
                    [],
                    graph.resolve("product.current:SOURCE@1#CLM-HIDDEN")[
                        "results"
                    ],
                )
                self.assertEqual(
                    1,
                    len(
                        graph.resolve("product.current:SOURCE@1#CLM-ACTIVE")
                        ["results"]
                    ),
                )

    def test_complete_html_block_starts_mask_relations_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="kg262-html-relations-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                body = "\n".join(
                    (
                        "# Source",
                        "",
                        "### CLM-SOURCE",
                        "",
                        "Active source claim.",
                        "",
                        html_start,
                        _relation_table("REL-HIDDEN", "SUPPORTS"),
                        "",
                        _relation_table("REL-ACTIVE", "DEPENDS_ON"),
                    )
                )
                (root / "source.md").write_text(
                    _document("SOURCE", body), encoding="utf-8"
                )

                graph = _load(root)
                relation_ids = [item["relation_id"] for item in graph.statements]
                self.assertNotIn("REL-HIDDEN", relation_ids)
                self.assertEqual(["REL-ACTIVE"], relation_ids)

    def test_complete_html_block_starts_mask_evidence_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="kg262-html-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(
                        ("SOURCE", "source.md"),
                        ("HIDDEN-EVIDENCE", "hidden-evidence.md"),
                        ("ACTIVE-EVIDENCE", "active-evidence.md"),
                    ),
                    encoding="utf-8",
                )
                source_body = "\n".join(
                    (
                        "# Source",
                        "",
                        "### CLM-SOURCE",
                        "",
                        "Active source claim.",
                        "",
                        html_start,
                        "#### Evidence",
                        "- [Hidden](hidden-evidence.md#CLM-HIDDEN-EVIDENCE)",
                        "",
                        "#### Evidence",
                        "",
                        "- [Active](active-evidence.md#CLM-ACTIVE-EVIDENCE)",
                    )
                )
                (root / "source.md").write_text(
                    _document("SOURCE", source_body), encoding="utf-8"
                )
                (root / "hidden-evidence.md").write_text(
                    _document(
                        "HIDDEN-EVIDENCE",
                        "### CLM-HIDDEN-EVIDENCE\n\nHidden evidence.",
                    ),
                    encoding="utf-8",
                )
                (root / "active-evidence.md").write_text(
                    _document(
                        "ACTIVE-EVIDENCE",
                        "### CLM-ACTIVE-EVIDENCE\n\nActive evidence.",
                    ),
                    encoding="utf-8",
                )

                graph = _load(root)
                source = graph.resolve("product.current:SOURCE@1#CLM-SOURCE")[
                    "results"
                ][0]
                hidden = graph.resolve(
                    "product.current:HIDDEN-EVIDENCE@1#CLM-HIDDEN-EVIDENCE"
                )["results"][0]
                active = graph.resolve(
                    "product.current:ACTIVE-EVIDENCE@1#CLM-ACTIVE-EVIDENCE"
                )["results"][0]
                self.assertFalse(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        hidden["occurrence_iri"],
                    )
                )
                self.assertTrue(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        active["occurrence_iri"],
                    )
                )

    def test_script_pre_style_and_textarea_stay_inactive_through_close_tag(self) -> None:
        for raw_tag in ("script", "pre", "style", "textarea"):
            with self.subTest(raw_tag=raw_tag), tempfile.TemporaryDirectory(
                prefix="kg262-html-raw-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                body = "\n".join(
                    (
                        "# Source",
                        "",
                        f"<{raw_tag}>",
                        "### CLM-HIDDEN",
                        "",
                        "Hidden despite the internal blank line.",
                        f"</{raw_tag}>",
                        "### CLM-ACTIVE",
                        "",
                        "Active after the raw close tag.",
                    )
                )
                (root / "source.md").write_text(
                    _document("SOURCE", body), encoding="utf-8"
                )

                graph = _load(root)
                self.assertEqual(
                    [],
                    graph.resolve("product.current:SOURCE@1#CLM-HIDDEN")[
                        "results"
                    ],
                )
                self.assertEqual(
                    1,
                    len(
                        graph.resolve("product.current:SOURCE@1#CLM-ACTIVE")
                        ["results"]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
