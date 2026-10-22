"""Markdown boundaries: only active Markdown may carry members, claims, relations, evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from okf_graph import graph as kg
from tests.helpers import (
    BASE_IRI,
    active_map,
    document,
    load,
    map_with_body,
    member_table,
    relation_table,
)


SUPPORTS = BASE_IRI + "/vocab/supports"
HTML_BLANK_TERMINATED_STARTS = ("</div>", "<div></div>", "<hr>", "<div />")
HTML_BLOCK_STARTS = ("<div>", '<x-probe data-mode="review">')
INACTIVE_KINDS = ("backtick_fence", "tilde_fence", "html_comment", "html_raw_block")


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


def _active_member_rows(*items: tuple) -> str:
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


def _resolved(graph, reference: str) -> list:
    return graph.resolve(reference)["results"]


class TestInactiveBlocks(unittest.TestCase):
    def test_inactive_members_tables_cannot_expand_the_map_closure(self) -> None:
        for ordinal, kind in enumerate(INACTIVE_KINDS + ("indented_code",), start=1):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="okfg-inactive-members-"
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
                graph = load(root)
                self.assertEqual({}, graph.documents)
                self.assertEqual(
                    [], _resolved(graph, f"product.current:{knowledge_id}@1#CLM-EXAMPLE")
                )

    def test_inactive_claim_headings_cannot_create_claims(self) -> None:
        for kind in INACTIVE_KINDS + ("indented_code",):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="okfg-inactive-claim-"
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
                graph = load(root)
                self.assertEqual([], _resolved(graph, "product.current:SOURCE@1#CLM-EXAMPLE"))

    def test_inactive_relations_emit_neither_direct_nor_reified_facts(self) -> None:
        relation = """#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-EXAMPLE` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `example` | [Self](source.md#CLM-SOURCE) |"""
        for kind in INACTIVE_KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="okfg-inactive-relation-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(_active_member_rows(("SOURCE", "source.md"))),
                    encoding="utf-8",
                )
                body = "# Source\n\n### CLM-SOURCE\n\nAn active claim.\n\n" + _wrap(
                    kind, relation
                )
                (root / "source.md").write_text(
                    _document_text("SOURCE", body), encoding="utf-8"
                )
                graph = load(root)
                self.assertEqual((), graph.statements)
                self.assertFalse(any(t.predicate == SUPPORTS for t in graph.triples))

    def test_inactive_evidence_links_cannot_ground_an_active_claim(self) -> None:
        evidence = "#### Evidence\n\n- [Example evidence](evidence.md#CLM-EVIDENCE)"
        for kind in INACTIVE_KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="okfg-inactive-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(
                        _active_member_rows(
                            ("SOURCE", "source.md"), ("EVIDENCE", "evidence.md")
                        )
                    ),
                    encoding="utf-8",
                )
                source_body = "# Source\n\n### CLM-SOURCE\n\nAn active claim.\n\n" + _wrap(
                    kind, evidence
                )
                (root / "source.md").write_text(
                    _document_text("SOURCE", source_body), encoding="utf-8"
                )
                (root / "evidence.md").write_text(
                    _document_text(
                        "EVIDENCE", "# Evidence\n\n### CLM-EVIDENCE\n\nAn active evidence claim."
                    ),
                    encoding="utf-8",
                )
                graph = load(root)
                source = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]
                evidence_claim = _resolved(graph, "product.current:EVIDENCE@1#CLM-EVIDENCE")[0]
                self.assertEqual([], source["evidence_paths"])
                self.assertEqual([], source["evidence_refs"])
                self.assertFalse(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        evidence_claim["occurrence_iri"],
                    )
                )


class TestHtmlBlocks(unittest.TestCase):
    def test_complete_html_block_starts_mask_members_until_blank_line(self) -> None:
        for ordinal, html_start in enumerate(HTML_BLANK_TERMINATED_STARTS, start=1):
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="okfg-html-members-"
            ) as tmp:
                root = Path(tmp)
                hidden_id = f"HIDDEN-{ordinal}"
                body = "\n".join(
                    (
                        html_start,
                        "## Members",
                        member_table(hidden_id, "hidden.md"),
                        "",
                        "## Members",
                        "",
                        member_table("ACTIVE", "active.md"),
                    )
                )
                (root / "knowledge-map.md").write_text(map_with_body(body), encoding="utf-8")
                (root / "hidden.md").write_text(
                    document(hidden_id, "### CLM-HIDDEN\n\nHidden."), encoding="utf-8"
                )
                (root / "active.md").write_text(
                    document("ACTIVE", "### CLM-ACTIVE\n\nActive."), encoding="utf-8"
                )

                graph = load(root)
                self.assertEqual(
                    [], _resolved(graph, f"product.current:{hidden_id}@1#CLM-HIDDEN")
                )
                self.assertEqual(
                    1, len(_resolved(graph, "product.current:ACTIVE@1#CLM-ACTIVE"))
                )

    def test_complete_html_block_starts_mask_claims_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="okfg-html-claims-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
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
                (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

                graph = load(root)
                self.assertEqual([], _resolved(graph, "product.current:SOURCE@1#CLM-HIDDEN"))
                self.assertEqual(
                    1, len(_resolved(graph, "product.current:SOURCE@1#CLM-ACTIVE"))
                )

    def test_complete_html_block_starts_mask_relations_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="okfg-html-relations-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
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
                        relation_table("REL-HIDDEN", "SUPPORTS"),
                        "",
                        relation_table("REL-ACTIVE", "DEPENDS_ON"),
                    )
                )
                (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

                graph = load(root)
                relation_ids = [item["relation_id"] for item in graph.statements]
                self.assertNotIn("REL-HIDDEN", relation_ids)
                self.assertEqual(["REL-ACTIVE"], relation_ids)

    def test_complete_html_block_starts_mask_evidence_until_blank_line(self) -> None:
        for html_start in HTML_BLANK_TERMINATED_STARTS:
            with self.subTest(html_start=html_start), tempfile.TemporaryDirectory(
                prefix="okfg-html-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(
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
                    document("SOURCE", source_body), encoding="utf-8"
                )
                (root / "hidden-evidence.md").write_text(
                    document("HIDDEN-EVIDENCE", "### CLM-HIDDEN-EVIDENCE\n\nHidden evidence."),
                    encoding="utf-8",
                )
                (root / "active-evidence.md").write_text(
                    document("ACTIVE-EVIDENCE", "### CLM-ACTIVE-EVIDENCE\n\nActive evidence."),
                    encoding="utf-8",
                )

                graph = load(root)
                source = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]
                hidden = _resolved(
                    graph, "product.current:HIDDEN-EVIDENCE@1#CLM-HIDDEN-EVIDENCE"
                )[0]
                active = _resolved(
                    graph, "product.current:ACTIVE-EVIDENCE@1#CLM-ACTIVE-EVIDENCE"
                )[0]
                references = kg.DCTERMS + "references"
                self.assertFalse(
                    graph.has_triple(source["occurrence_iri"], references, hidden["occurrence_iri"])
                )
                self.assertTrue(
                    graph.has_triple(source["occurrence_iri"], references, active["occurrence_iri"])
                )

    def test_script_pre_style_and_textarea_stay_inactive_through_close_tag(self) -> None:
        for raw_tag in ("script", "pre", "style", "textarea"):
            with self.subTest(raw_tag=raw_tag), tempfile.TemporaryDirectory(
                prefix="okfg-html-raw-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
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
                (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

                graph = load(root)
                self.assertEqual([], _resolved(graph, "product.current:SOURCE@1#CLM-HIDDEN"))
                self.assertEqual(
                    1, len(_resolved(graph, "product.current:SOURCE@1#CLM-ACTIVE"))
                )

    def test_blank_line_ends_html_block_before_active_members_table(self) -> None:
        for ordinal, start in enumerate(HTML_BLOCK_STARTS, start=1):
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="okfg-html-blank-members-"
            ) as tmp:
                root = Path(tmp)
                knowledge_id = f"ACTIVE-{ordinal}"
                path = f"active-{ordinal}.md"
                (root / "knowledge-map.md").write_text(
                    map_with_body(
                        "## Members\n\n" + start + "\n\n" + member_table(knowledge_id, path)
                    ),
                    encoding="utf-8",
                )
                (root / path).write_text(
                    document(knowledge_id, "### CLM-ACTIVE\n\nThis claim is active."),
                    encoding="utf-8",
                )

                graph = load(root)

                self.assertIn(f"product.current:{knowledge_id}@1", graph.documents)

    def test_blank_line_ends_html_block_before_active_claim(self) -> None:
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="okfg-html-blank-claim-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                (root / "source.md").write_text(
                    document(
                        "SOURCE", start + "\n\n### CLM-ACTIVE\n\nThis claim follows the block."
                    ),
                    encoding="utf-8",
                )

                graph = load(root)

                self.assertEqual(
                    1, len(_resolved(graph, "product.current:SOURCE@1#CLM-ACTIVE"))
                )

    def test_blank_line_ends_html_block_before_active_relation(self) -> None:
        relation = """#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-ACTIVE` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `active` | [Self](source.md#CLM-SOURCE) |"""
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="okfg-html-blank-relation-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                (root / "source.md").write_text(
                    document(
                        "SOURCE",
                        "### CLM-SOURCE\n\nAn active claim.\n\n" + start + "\n\n" + relation,
                    ),
                    encoding="utf-8",
                )

                graph = load(root)

                self.assertEqual(1, len(graph.statements))
                self.assertTrue(any(t.predicate == SUPPORTS for t in graph.triples))

    def test_blank_line_ends_html_block_before_active_evidence(self) -> None:
        evidence = "#### Evidence\n\n- [Active evidence](evidence.md#CLM-EVIDENCE)"
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="okfg-html-blank-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md"), ("EVIDENCE", "evidence.md")),
                    encoding="utf-8",
                )
                (root / "source.md").write_text(
                    document(
                        "SOURCE",
                        "### CLM-SOURCE\n\nAn active claim.\n\n" + start + "\n\n" + evidence,
                    ),
                    encoding="utf-8",
                )
                (root / "evidence.md").write_text(
                    document("EVIDENCE", "### CLM-EVIDENCE\n\nActive evidence."),
                    encoding="utf-8",
                )

                graph = load(root)
                source = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]
                evidence_claim = _resolved(graph, "product.current:EVIDENCE@1#CLM-EVIDENCE")[0]

                self.assertEqual(
                    ["product.current:EVIDENCE@1#CLM-EVIDENCE"], source["evidence_refs"]
                )
                self.assertTrue(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        evidence_claim["occurrence_iri"],
                    )
                )

    def test_type6_end_of_line_start_masks_every_graph_surface_until_blank(self) -> None:
        for surface in ("## Members", "### CLM-HIDDEN", "#### Relations", "#### Evidence"):
            with self.subTest(surface=surface):
                lines = ["<div", surface, "", "### CLM-ACTIVE"]
                self.assertEqual(
                    ["", "", "", "### CLM-ACTIVE"], kg._active_markdown_lines(lines)
                )

    def test_type6_end_of_line_start_cannot_select_hidden_members_table(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-html-eol-members-") as tmp:
            root = Path(tmp)
            body = "\n".join(
                (
                    "<div",
                    "## Members",
                    member_table("HIDDEN", "hidden.md"),
                    "",
                    "## Members",
                    "",
                    member_table("ACTIVE", "active.md"),
                )
            )
            (root / "knowledge-map.md").write_text(map_with_body(body), encoding="utf-8")
            (root / "hidden.md").write_text(
                document("HIDDEN", "### CLM-HIDDEN\n\nHidden."), encoding="utf-8"
            )
            (root / "active.md").write_text(
                document("ACTIVE", "### CLM-ACTIVE\n\nActive."), encoding="utf-8"
            )

            graph = load(root)

            self.assertEqual([], _resolved(graph, "product.current:HIDDEN@1#CLM-HIDDEN"))
            self.assertEqual(1, len(_resolved(graph, "product.current:ACTIVE@1#CLM-ACTIVE")))


class TestComments(unittest.TestCase):
    def test_multiline_comment_close_line_cannot_create_members_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-comment-members-") as tmp:
            root = Path(tmp)
            body = "\n".join(
                (
                    "<!--",
                    "-->## Members",
                    member_table("FABRICATED", "fabricated.md"),
                    "",
                    "## Members",
                    "",
                    member_table("ACTIVE", "active.md"),
                )
            )
            (root / "knowledge-map.md").write_text(map_with_body(body), encoding="utf-8")
            (root / "fabricated.md").write_text(
                document("FABRICATED", "### CLM-FAB\n\nFabricated."), encoding="utf-8"
            )
            (root / "active.md").write_text(
                document("ACTIVE", "### CLM-ACTIVE\n\nActive."), encoding="utf-8"
            )

            graph = load(root)

            self.assertNotIn("product.current:FABRICATED@1", graph.documents)
            self.assertIn("product.current:ACTIVE@1", graph.documents)

    def test_multiline_comment_close_line_cannot_create_claim_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-comment-claim-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            body = "\n".join(
                (
                    "<!--",
                    "-->### CLM-FAB",
                    "Fabricated claim.",
                    "",
                    "### CLM-ACTIVE",
                    "",
                    "Active claim.",
                )
            )
            (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

            graph = load(root)

            self.assertEqual([], _resolved(graph, "product.current:SOURCE@1#CLM-FAB"))
            self.assertEqual(1, len(_resolved(graph, "product.current:SOURCE@1#CLM-ACTIVE")))

    def test_multiline_comment_close_line_cannot_create_relations_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-comment-relation-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            relation = """<!--
-->#### Relations
| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-FAB` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `fabricated` | [Self](source.md#CLM-SOURCE) |"""
            (root / "source.md").write_text(
                document("SOURCE", "### CLM-SOURCE\n\nActive claim.\n\n" + relation),
                encoding="utf-8",
            )

            graph = load(root)

            self.assertEqual((), graph.statements)
            self.assertFalse(any(t.predicate == SUPPORTS for t in graph.triples))

    def test_multiline_comment_close_line_cannot_create_evidence_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-comment-evidence-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                active_map(("SOURCE", "source.md"), ("EVIDENCE", "evidence.md")),
                encoding="utf-8",
            )
            evidence = "<!--\n-->#### Evidence\n- [Fabricated evidence](evidence.md#CLM-EVIDENCE)"
            (root / "source.md").write_text(
                document("SOURCE", "### CLM-SOURCE\n\nActive claim.\n\n" + evidence),
                encoding="utf-8",
            )
            (root / "evidence.md").write_text(
                document("EVIDENCE", "### CLM-EVIDENCE\n\nIndependent evidence."),
                encoding="utf-8",
            )

            graph = load(root)
            source = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]

            self.assertEqual([], source["evidence_refs"])

    def test_leading_single_line_html_comment_owns_complete_line(self) -> None:
        for spaces in (0, 1, 2, 3):
            line = " " * spaces + "<!-- sample -->### CLM-FAB"
            with self.subTest(spaces=spaces):
                self.assertEqual([""], kg._active_markdown_lines([line]))

        self.assertEqual(
            ["Active text  remains active."],
            kg._active_markdown_lines(["Active text <!-- inline note --> remains active."]),
        )

    def test_leading_single_line_comment_cannot_create_claim(self) -> None:
        for spaces in (0, 1, 2, 3):
            with self.subTest(spaces=spaces), tempfile.TemporaryDirectory(
                prefix="okfg-leading-comment-claim-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                body = (
                    " " * spaces
                    + "<!-- sample -->### CLM-FAB\nFabricated.\n\n"
                    + "### CLM-ACTIVE\n\nActive."
                )
                (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

                graph = load(root)

                self.assertEqual([], _resolved(graph, "product.current:SOURCE@1#CLM-FAB"))
                self.assertEqual(
                    1, len(_resolved(graph, "product.current:SOURCE@1#CLM-ACTIVE"))
                )

    def test_leading_single_line_block_comment_masks_all_graph_surface_suffixes(self) -> None:
        for surface in ("## Members", "### CLM-FAB", "#### Relations", "#### Evidence"):
            for spaces in (0, 1, 2, 3):
                line = " " * spaces + "<!-- sample -->" + surface
                with self.subTest(surface=surface, spaces=spaces):
                    self.assertEqual([""], kg._active_markdown_lines([line]))


class TestClaimScope(unittest.TestCase):
    def test_h1_h2_or_h3_heading_ends_claim_provenance_scope(self) -> None:
        relation = """#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-APPENDIX` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `appendix` | [Self](source.md#CLM-SOURCE) |"""
        evidence = "#### Evidence\n\n- [Appendix evidence](evidence.md#CLM-EVIDENCE)"
        for heading in ("# Appendix", "## Appendix", "### Appendix"):
            with self.subTest(heading=heading), tempfile.TemporaryDirectory(
                prefix="okfg-claim-scope-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    active_map(("SOURCE", "source.md"), ("EVIDENCE", "evidence.md")),
                    encoding="utf-8",
                )
                source_body = (
                    "### CLM-SOURCE\n\nGrounded source claim.\n\n"
                    + heading
                    + "\n\nUnrelated appendix.\n\n"
                    + relation
                    + "\n\n"
                    + evidence
                )
                (root / "source.md").write_text(
                    document("SOURCE", source_body), encoding="utf-8"
                )
                (root / "evidence.md").write_text(
                    document("EVIDENCE", "### CLM-EVIDENCE\n\nIndependent evidence."),
                    encoding="utf-8",
                )

                graph = load(root)
                claim = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]

                self.assertEqual("Grounded source claim.", claim["claim_text"])
                self.assertEqual([], claim["evidence_refs"])
                self.assertEqual((), graph.statements)
                self.assertFalse(any(t.predicate == SUPPORTS for t in graph.triples))

    def test_indented_h2_or_h3_heading_ends_claim_provenance_scope(self) -> None:
        relation = """#### Relations
| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-INDENT` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `appendix` | [Self](source.md#CLM-SOURCE) |"""
        for spaces in (1, 2, 3):
            for level in (2, 3):
                heading = " " * spaces + "#" * level + " Appendix"
                with self.subTest(heading=heading), tempfile.TemporaryDirectory(
                    prefix="okfg-claim-indent-scope-"
                ) as tmp:
                    root = Path(tmp)
                    (root / "knowledge-map.md").write_text(
                        active_map(("SOURCE", "source.md")), encoding="utf-8"
                    )
                    body = (
                        "### CLM-SOURCE\n\nGrounded claim.\n\n"
                        + heading
                        + "\n\nAppendix.\n\n"
                        + relation
                    )
                    (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")

                    graph = load(root)
                    claim = _resolved(graph, "product.current:SOURCE@1#CLM-SOURCE")[0]

                    self.assertEqual("Grounded claim.", claim["claim_text"])
                    self.assertEqual((), graph.statements)
                    self.assertFalse(any(t.predicate == SUPPORTS for t in graph.triples))


if __name__ == "__main__":
    unittest.main()
