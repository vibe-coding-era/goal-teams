from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "6" * 64
PROFILE_SHA256 = "5" * 64


def _load(root: Path):
    return kg.load_current_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


def _map_text(rows: str) -> str:
    return f"""---
type: Knowledge Map
title: Active Markdown map
description: Only active simple tables may authorize closure members.
timestamp: 2026-08-08T01:00:00+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: product.current
knowledge_id: MAP-ACTIVE-MARKDOWN
revision: "1"
owner: parser-owner
lifecycle: current
modality: collection-map
epistemic_state: documented
sensitivity: internal
---

# Active Markdown map

## Members

{rows}
"""


def _document_text(knowledge_id: str, body: str) -> str:
    return f"""---
type: Knowledge Note
title: Active Markdown document
description: Examples cannot become graph facts.
timestamp: 2026-08-08T01:00:01+08:00
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

{body}
"""


def _member_row(knowledge_id: str, path: str) -> str:
    return (
        "| member_ref | path | member_kind | lifecycle |\n"
        "| --- | --- | --- | --- |\n"
        f"| `product.current:{knowledge_id}@1` | [Example]({path}) | "
        "`Knowledge Note` | `current` |"
    )


def _active_member_rows(*items: tuple[str, str]) -> str:
    rows = [
        "| member_ref | path | member_kind | lifecycle |",
        "| --- | --- | --- | --- |",
    ]
    rows.extend(
        f"| `product.current:{knowledge_id}@1` | [Member]({path}) | "
        "`Knowledge Note` | `current` |"
        for knowledge_id, path in items
    )
    return "\n".join(rows)


def _wrap(kind: str, text: str) -> str:
    if kind == "backtick_fence":
        return "```markdown\n" + text + "\n```"
    if kind == "tilde_fence":
        return "~~~markdown\n" + text + "\n~~~"
    if kind == "html_comment":
        return "<!--\n" + text + "\n-->"
    if kind == "html_raw_block":
        return "<div>\n" + text + "\n</div>\n"
    if kind == "indented_code":
        return "\n".join("    " + line for line in text.splitlines())
    raise AssertionError(kind)


class TestV262KnowledgeGraphAdversarialRound6(unittest.TestCase):
    def test_inactive_members_tables_cannot_expand_the_map_closure(self) -> None:
        kinds = (
            "backtick_fence",
            "tilde_fence",
            "html_comment",
            "html_raw_block",
            "indented_code",
        )
        for ordinal, kind in enumerate(kinds, start=1):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="kg262-inactive-members-"
            ) as tmp:
                root = Path(tmp)
                knowledge_id = f"EXAMPLE-{ordinal}"
                path = f"example-{ordinal}.md"
                (root / "knowledge-map.md").write_text(
                    _map_text(_wrap(kind, _member_row(knowledge_id, path))),
                    encoding="utf-8",
                )
                (root / path).write_text(
                    _document_text(knowledge_id, "### CLM-EXAMPLE\n\nExample."),
                    encoding="utf-8",
                )
                graph = _load(root)
                self.assertEqual({}, graph.documents)
                self.assertEqual(
                    [],
                    graph.resolve(
                        f"product.current:{knowledge_id}@1#CLM-EXAMPLE"
                    )["results"],
                )

    def test_inactive_claim_headings_cannot_create_claims(self) -> None:
        kinds = (
            "backtick_fence",
            "tilde_fence",
            "html_comment",
            "html_raw_block",
            "indented_code",
        )
        for kind in kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="kg262-inactive-claim-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(_active_member_rows(("SOURCE", "source.md"))),
                    encoding="utf-8",
                )
                body = "# Source\n\n" + _wrap(
                    kind, "### CLM-EXAMPLE\n\nThis is sample syntax only."
                )
                (root / "source.md").write_text(
                    _document_text("SOURCE", body), encoding="utf-8"
                )
                graph = _load(root)
                self.assertEqual(
                    [],
                    graph.resolve("product.current:SOURCE@1#CLM-EXAMPLE")[
                        "results"
                    ],
                )

    def test_inactive_relations_emit_neither_direct_nor_reified_facts(self) -> None:
        relation_table = """#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-EXAMPLE` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `example` | [Self](source.md#CLM-SOURCE) |"""
        for kind in (
            "backtick_fence",
            "tilde_fence",
            "html_comment",
            "html_raw_block",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="kg262-inactive-relation-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(_active_member_rows(("SOURCE", "source.md"))),
                    encoding="utf-8",
                )
                body = (
                    "# Source\n\n### CLM-SOURCE\n\nAn active claim.\n\n"
                    + _wrap(kind, relation_table)
                )
                (root / "source.md").write_text(
                    _document_text("SOURCE", body), encoding="utf-8"
                )
                graph = _load(root)
                self.assertEqual((), graph.statements)
                self.assertFalse(
                    any(
                        triple.predicate == BASE_IRI + "/vocab/supports"
                        for triple in graph.triples
                    )
                )

    def test_inactive_evidence_links_cannot_ground_an_active_claim(self) -> None:
        evidence_example = """#### Evidence

- [Example evidence](evidence.md#CLM-EVIDENCE)"""
        for kind in (
            "backtick_fence",
            "tilde_fence",
            "html_comment",
            "html_raw_block",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="kg262-inactive-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(
                        _active_member_rows(
                            ("SOURCE", "source.md"),
                            ("EVIDENCE", "evidence.md"),
                        )
                    ),
                    encoding="utf-8",
                )
                source_body = (
                    "# Source\n\n### CLM-SOURCE\n\nAn active claim.\n\n"
                    + _wrap(kind, evidence_example)
                )
                (root / "source.md").write_text(
                    _document_text("SOURCE", source_body), encoding="utf-8"
                )
                (root / "evidence.md").write_text(
                    _document_text(
                        "EVIDENCE",
                        "# Evidence\n\n### CLM-EVIDENCE\n\nAn active evidence claim.",
                    ),
                    encoding="utf-8",
                )
                graph = _load(root)
                source = graph.resolve(
                    "product.current:SOURCE@1#CLM-SOURCE"
                )["results"][0]
                evidence = graph.resolve(
                    "product.current:EVIDENCE@1#CLM-EVIDENCE"
                )["results"][0]
                self.assertEqual([], source["evidence_paths"])
                self.assertEqual([], source["evidence_refs"])
                self.assertFalse(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        evidence["occurrence_iri"],
                    )
                )


if __name__ == "__main__":
    unittest.main()
