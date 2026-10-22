"""Shared paths, loaders and Markdown builders for the okf-graph tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from okf_graph import graph as kg


EXTRA_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASIC = FIXTURES / "basic"
BASE_IRI = "https://kg.example.invalid/okf"


def load(
    root: Path,
    *,
    base_iri: str = BASE_IRI,
    entry_map: str = kg.DEFAULT_ENTRY_MAP,
):
    """Load in map mode, failing if the map is missing (never falls back)."""

    return kg.load_graph(root, entry_map=entry_map, kg_base_iri=base_iri)


def copy_basic(parent: Path, name: str = "basic") -> Path:
    root = parent / name
    shutil.copytree(BASIC, root)
    return root


def replace_text(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"fixture token missing: {old!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


def frontmatter(*, knowledge_id: str, document_type: str = "Knowledge Note") -> str:
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


def member_table(knowledge_id: str, path: str) -> str:
    return "\n".join(
        (
            "| member_ref | path | member_kind | lifecycle |",
            "| --- | --- | --- | --- |",
            f"| `product.current:{knowledge_id}@1` | [Member]({path}) | "
            "`Knowledge Note` | `current` |",
        )
    )


def map_with_body(body: str) -> str:
    return (
        frontmatter(knowledge_id="MAP-HTML-BLOCK", document_type="Knowledge Map")
        + "\n# HTML block map\n\n"
        + body
        + "\n"
    )


def document(knowledge_id: str, body: str) -> str:
    return frontmatter(knowledge_id=knowledge_id) + "\n" + body + "\n"


def active_map(*items: tuple[str, str]) -> str:
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
    return map_with_body("\n".join(rows))


def relation_table(relation_id: str, predicate: str) -> str:
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
