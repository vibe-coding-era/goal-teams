#!/usr/bin/env python3
"""Command line for the optional OKF document graph.

  build   DIR [--format ntriples|json] [--out FILE]   print or write the graph
  lookup  DIR LABEL-OR-IRI [--json]                    find nodes by IRI, reference or text
  quality DIR [--json]                                 print Observe-only findings

Every command also takes --map FILE | --file FILE..., and --base-iri IRI.
Exit codes: 0 ok; 1 lookup matched nothing; 2 usage or input error.
Quality findings never change the exit code.  Python 3.9+, stdlib only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from typing import Any, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:  # also works under ``python -I``
    sys.path.insert(0, _HERE)

from okf_graph import DEFAULT_KG_BASE_IRI, DocumentGraph, GraphSecurityError, load_graph  # noqa: E402

PROG = "okf_graph_cli.py"
EXPORT_SCHEMA = "okf-docgraph-export-v0.5"


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("dir", metavar="DIR", help="trusted directory of OKF Markdown")
    members = common.add_mutually_exclusive_group()
    members.add_argument(
        "--map",
        dest="entry_map",
        metavar="FILE",
        help="entry map relative to DIR (default: knowledge-map.md if present)",
    )
    members.add_argument(
        "--file",
        dest="files",
        action="append",
        metavar="FILE",
        help="explicit member file relative to DIR (repeatable)",
    )
    common.add_argument(
        "--base-iri",
        default=DEFAULT_KG_BASE_IRI,
        metavar="IRI",
        help=f"normalized HTTPS base for minted IRIs (default: {DEFAULT_KG_BASE_IRI})",
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="In-memory OKF Markdown -> RDF document graph (Observe-only).",
        epilog="exit codes: 0 ok, 1 lookup matched nothing, 2 usage or input error",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.required = True
    build = commands.add_parser(
        "build", parents=[common], help="print the graph as N-Triples or JSON"
    )
    build.add_argument("--format", choices=("ntriples", "json"), default="ntriples")
    build.add_argument("--out", metavar="FILE", help="write to FILE instead of stdout")
    lookup = commands.add_parser(
        "lookup", parents=[common], help="find nodes by IRI, reference or label text"
    )
    lookup.add_argument(
        "query",
        metavar="LABEL-OR-IRI",
        help="an IRI, a reference (ns:id@rev[#CLM-...] or ns:id), or label text",
    )
    lookup.add_argument("--json", action="store_true", help="print the query receipt")
    quality = commands.add_parser(
        "quality", parents=[common], help="print Observe-only findings (exit 0)"
    )
    quality.add_argument("--json", action="store_true", help="print the observe receipt")
    return parser


def _write_stdout(text: str) -> None:
    """Write UTF-8 regardless of the locale (N-Triples is UTF-8 by definition)."""

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _export(graph: DocumentGraph) -> dict[str, Any]:
    return {
        "schema": EXPORT_SCHEMA,
        "receipt": graph.to_receipt(),
        "graph_input": graph.graph_input,
        "documents": graph.documents,
        "claims": graph.claims,
        "statements": list(graph.statements),
        "observations": list(graph.observations),
        "triples": [dataclasses.asdict(triple) for triple in graph.triples],
    }


def _build(graph: DocumentGraph, args: argparse.Namespace) -> int:
    text = _json(_export(graph)) if args.format == "json" else graph.to_ntriples()
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        _write_stdout(text)
    receipt = graph.to_receipt()
    print(
        f"{PROG}: {receipt['document_count']} documents, {len(graph.claims)} claims, "
        f"{receipt['triple_count']} triples, {receipt['observation_count']} findings"
        " (observe-only)" + (f" -> {args.out}" if args.out else ""),
        file=sys.stderr,
    )
    return 0


def _render_lookup(graph: DocumentGraph, receipt: dict[str, Any]) -> str:
    claim_by_iri = {item["occurrence_iri"]: ref for ref, item in graph.claims.items()}
    lines = [
        f"lookup: {receipt['match_count']} match(es), {receipt['match_state']}, "
        f"by {receipt['lookup_mode']}"
        + (f" (first {len(receipt['results'])} shown)" if receipt["truncated"] else "")
    ]
    for item in receipt["results"]:
        kind = item["result_kind"]
        if kind == "statement":
            lines.append(f"* statement {item['iri']}")
            lines.append(
                f"  {claim_by_iri.get(item['subject'], item['subject'])} "
                f"<{item['predicate']}> "
                f"{claim_by_iri.get(item['object'], item['object'])} "
                f"({item['assertion_state']})"
            )
            continue
        if kind == "search_hit":
            lines.append(f"* {item['reference']}  ({item['path']})")
            lines.append(f"  title: {item['title']}")
            for claim_ref in item["claim_refs"]:
                lines.append(f"  claim: {claim_ref}")
            continue
        lines.append(f"* {kind} {item['reference']}")
        lines.append(f"  path:  {item['source_anchor']}")
        if kind == "document":
            lines.append(f"  title: {item['title']}")
            lines.append(f"  iri:   {item['revision_iri']}")
            for claim_ref in item["claim_refs"]:
                lines.append(f"  claim: {claim_ref}")
            continue
        lines.append(f"  iri:   {item['occurrence_iri']}")
        lines.append(f"  text:  {' / '.join(item['claim_text'].splitlines())}")
        for edge in graph.neighbors(item["reference"], limit=10_000)["results"]:
            if edge["subject_ref"] == item["reference"]:
                lines.append(f"  -> {edge['predicate_name']} {edge['object_ref']}")
            else:
                lines.append(f"  <- {edge['predicate_name']} {edge['subject_ref']}")
        for evidence_ref in item["evidence_refs"]:
            lines.append(f"  evidence: {evidence_ref}")
    return "\n".join(lines) + "\n"


def _lookup(graph: DocumentGraph, args: argparse.Namespace) -> int:
    receipt = graph.lookup(args.query)
    _write_stdout(_json(receipt) if args.json else _render_lookup(graph, receipt))
    return 0 if receipt["match_count"] else 1


def _quality(graph: DocumentGraph, args: argparse.Namespace) -> int:
    receipt = graph.observe(limit=10_000)
    if args.json:
        _write_stdout(_json(receipt))
        return 0
    results = receipt["results"]
    lines = [
        f"quality: {receipt['match_count']} finding(s), coverage {receipt['coverage_state']}"
        " (Observe-only: recorded, never blocking)"
    ]
    for item in results:
        lines.append(f"[{item['severity']}] {item['rule_id']}  {item['subject_ref']}")
        lines.append("    " + json.dumps(item["detail"], ensure_ascii=False, sort_keys=True))
    if receipt["truncated"]:
        lines.append(f"(first {len(results)} of {receipt['match_count']} shown)")
    if not results:
        lines.append("No findings from the implemented detectors; this is not a pass verdict.")
    _write_stdout("\n".join(lines) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        graph = load_graph(
            args.dir, args.files, entry_map=args.entry_map, kg_base_iri=args.base_iri
        )
        if args.command == "build":
            return _build(graph, args)
        if args.command == "lookup":
            return _lookup(graph, args)
        return _quality(graph, args)
    except GraphSecurityError as exc:
        print(f"{PROG}: error: {exc.code}: {exc.message}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # The reader closed stdout early (e.g. ``| head``): stop quietly.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (OSError, ValueError) as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
