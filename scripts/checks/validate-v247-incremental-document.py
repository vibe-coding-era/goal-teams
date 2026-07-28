#!/usr/bin/env python3
"""Validate V2.47 incremental document CAS, hashes and projection."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "incremental-document-manifest.json"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_exact_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    keys = set(value)
    if missing := sorted(required - keys):
        fail(f"{label} missing fields: {missing}")
    if unknown := sorted(keys - required - optional):
        fail(f"{label} unknown fields: {unknown}")


def stable_prefix_digest(segments: list[str]) -> str:
    payload = json.dumps(
        segments, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compile_projection(fragments: list[dict[str, Any]]) -> tuple[str, int]:
    ordered = sorted(
        fragments,
        key=lambda item: (
            item["base_revision"],
            item["new_revision"],
            item["fragment_id"],
        ),
    )
    current_revision = 0
    section_order: list[str] = []
    sections: dict[str, str] = {}
    fragment_ids: set[str] = set()
    for item in ordered:
        fragment_id = item["fragment_id"]
        if fragment_id in fragment_ids:
            fail(f"duplicate fragment_id: {fragment_id}")
        fragment_ids.add(fragment_id)
        if item["base_revision"] != current_revision:
            fail(f"{fragment_id} CAS base revision mismatch")
        if item["new_revision"] != current_revision + 1:
            fail(f"{fragment_id} revision must advance exactly once")
        content = item["content"]
        if sha256_text(content) != item["content_sha256"]:
            fail(f"{fragment_id} content hash mismatch")
        section_id = item["section_id"]
        operation = item["operation"]
        if operation == "append":
            if section_id in sections:
                fail(f"{fragment_id} append cannot overwrite section")
            section_order.append(section_id)
            sections[section_id] = content
        elif operation == "replace_section":
            if section_id not in sections:
                fail(f"{fragment_id} replace target missing")
            sections[section_id] = content
        elif operation == "tombstone":
            if section_id not in sections:
                fail(f"{fragment_id} tombstone target missing")
            del sections[section_id]
            section_order.remove(section_id)
        else:
            fail(f"{fragment_id} operation unsupported")
        current_revision = item["new_revision"]
    projection = "".join(sections[key] for key in section_order if key in sections)
    return projection, current_revision


def validate(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"manifest unreadable: {exc}")
    if manifest.get("schema_version") != "goal-teams-incremental-document-v2.47":
        fail("schema_version mismatch")
    require_exact_keys(
        manifest,
        {
            "schema_version",
            "product_version",
            "schema",
            "validator",
            "operations",
            "ordering",
            "stable_prefix_encoding",
            "runtime_integration_state",
            "p0_projection_fixture",
        },
        set(),
        "manifest",
    )
    if manifest.get("product_version") != "V2.47":
        fail("product_version mismatch")
    if manifest.get("operations") != ["append", "replace_section", "tombstone"]:
        fail("operation denominator drift")
    if manifest.get("ordering") != [
        "base_revision",
        "new_revision",
        "fragment_id",
    ]:
        fail("projection ordering drift")
    if (
        manifest.get("runtime_integration_state")
        != "contract_p0_not_runtime_integrated"
    ):
        fail("runtime integration state overclaims implementation")
    for field in ("schema", "validator"):
        relative = manifest.get(field)
        if not isinstance(relative, str) or not (ROOT / relative).is_file():
            fail(f"missing declared file for {field}: {relative!r}")

    fixture = manifest.get("p0_projection_fixture")
    if not isinstance(fixture, dict):
        fail("p0_projection_fixture missing")
    require_exact_keys(
        fixture,
        {
            "document_id",
            "stable_prefix",
            "stable_prefix_sha256",
            "dynamic_tail_a",
            "dynamic_tail_b",
            "fragments",
            "expected_projection",
            "expected_projection_sha256",
            "expected_revision",
        },
        set(),
        "p0_projection_fixture",
    )
    stable_prefix = fixture.get("stable_prefix")
    if not isinstance(stable_prefix, list) or not all(
        isinstance(value, str) for value in stable_prefix
    ):
        fail("stable prefix invalid")
    dynamic_tail_a = fixture.get("dynamic_tail_a")
    dynamic_tail_b = fixture.get("dynamic_tail_b")
    if not isinstance(dynamic_tail_a, list) or not isinstance(dynamic_tail_b, list):
        fail("dynamic tails must be arrays")
    prefix_bytes = json.dumps(
        stable_prefix, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    marker = b"\n---dynamic-tail---\n"
    request_a = prefix_bytes + marker + json.dumps(dynamic_tail_a).encode("utf-8")
    request_b = prefix_bytes + marker + json.dumps(dynamic_tail_b).encode("utf-8")
    prefix_digest_a = hashlib.sha256(request_a[: len(prefix_bytes)]).hexdigest()
    prefix_digest_b = hashlib.sha256(request_b[: len(prefix_bytes)]).hexdigest()
    if (
        prefix_digest_a != fixture.get("stable_prefix_sha256")
        or prefix_digest_b != prefix_digest_a
    ):
        fail("stable prefix digest changed with dynamic tail")
    fragments = fixture.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        fail("fragments missing")
    fragment_fields = {
        "document_id",
        "fragment_id",
        "base_revision",
        "new_revision",
        "section_id",
        "operation",
        "content_ref",
        "content",
        "content_sha256",
        "actor_run_id",
        "created_at",
    }
    for fragment in fragments:
        if not isinstance(fragment, dict):
            fail("fragment must be an object")
        require_exact_keys(fragment, fragment_fields, set(), "fragment")
        if fragment.get("document_id") != fixture.get("document_id"):
            fail("fragment document_id mismatch")
        for field in ("fragment_id", "section_id", "content_ref", "actor_run_id"):
            if not isinstance(fragment.get(field), str) or not fragment[field]:
                fail(f"fragment {field} must be a non-empty string")
        created_at = fragment.get("created_at")
        if not isinstance(created_at, str) or RFC3339_PATTERN.fullmatch(created_at) is None:
            fail("fragment created_at must be an RFC3339 string")
        try:
            parsed_created_at = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
        except ValueError:
            fail("fragment created_at must be an RFC3339 string")
        if parsed_created_at.tzinfo is None:
            fail("fragment created_at must include a timezone")
    projection_a, revision_a = compile_projection(fragments)
    projection_b, revision_b = compile_projection(list(reversed(fragments)))
    if projection_a != projection_b or revision_a != revision_b:
        fail("projection is not deterministic under input order")
    if projection_a != fixture.get("expected_projection"):
        fail("projection bytes mismatch")
    if sha256_text(projection_a) != fixture.get("expected_projection_sha256"):
        fail("projection digest mismatch")
    if revision_a != fixture.get("expected_revision"):
        fail("projection revision mismatch")
    return {
        "ok": True,
        "fragment_count": len(fragments),
        "final_revision": revision_a,
        "stable_prefix_digest_unchanged": True,
        "projection_byte_equivalent": True,
        "runtime_integration_state": manifest["runtime_integration_state"],
        "full_regression_executed": False,
    }


if __name__ == "__main__":
    selected = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_MANIFEST
    if len(sys.argv) > 2:
        fail("usage: validate-v247-incremental-document.py [manifest.json]")
    json.dump(validate(selected), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
