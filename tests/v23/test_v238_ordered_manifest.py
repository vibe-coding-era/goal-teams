"""Adversarial tests for the V2.38 host-observed ordered prompt manifest."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT


def _load_runtime():
    path = ROOT / "scripts" / "v23" / "prompt_cache.py"
    spec = importlib.util.spec_from_file_location(
        "goalteams_v238_ordered_manifest_test", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prompt_cache = _load_runtime()


def _segment(order: int, segment_id: str, segment_class: str) -> dict[str, object]:
    payload = f"{segment_id}:{segment_class}".encode("utf-8")
    if segment_class == "platform_managed":
        source_type = "host"
        source_ref = f"sha256:{hashlib.sha256(segment_id.encode()).hexdigest()}"
    elif segment_class == "stable":
        source_type = "file"
        source_ref = "SKILL.md"
    else:
        source_type = "user"
        source_ref = "redacted:user_request"
    return {
        "order": order,
        "segment_id": segment_id,
        "segment_class": segment_class,
        "source_type": source_type,
        "source_ref": source_ref,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_count": len(payload),
        "token_count": None,
        "token_count_status": "unavailable",
        "inclusion_reason": "effective_provider_request",
        "inclusion_state": "included",
        "redaction_state": "content_not_persisted",
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "goal-teams-ordered-prompt-manifest-v1",
        "manifest_id": "PM-RUN-1-TURN-1",
        "product_version": "V2.38",
        "agent_run_id": "RUN-1",
        "turn_id": "TURN-1",
        "route_id": "benchmark",
        "policy_profile": "goal-teams-core-v2.5",
        "manifest_status": "available",
        "digest_scope": "complete",
        "missing_segment_classes": [],
        "stable_segment_count": 1,
        "dynamic_segment_count": 1,
        "platform_managed_segment_count": 1,
        "canonicalization": "utf8-lf-json-jcs-v1",
        "segments": [
            _segment(0, "host", "platform_managed"),
            _segment(1, "goal-teams", "stable"),
            _segment(2, "request", "dynamic"),
        ],
    }


class OrderedPromptManifestTests(unittest.TestCase):
    def test_platform_managed_then_stable_then_dynamic_is_valid(self) -> None:
        identity = prompt_cache.build_ordered_prompt_identity(_manifest())
        self.assertEqual(identity["manifest_status"], "available")
        self.assertEqual(identity["digest_scope"], "complete")
        self.assertEqual(identity["platform_managed_segment_count"], 1)
        self.assertEqual(identity["stable_segment_count"], 1)
        self.assertEqual(identity["stable_prefix_segment_count"], 2)
        self.assertRegex(identity["stable_prefix_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(identity["runtime_prompt_digest"], r"^[0-9a-f]{64}$")

    def test_manifest_identity_fields_are_required_and_version_bound(self) -> None:
        for field in (
            "manifest_id",
            "product_version",
            "agent_run_id",
            "turn_id",
            "route_id",
            "policy_profile",
        ):
            candidate = _manifest()
            candidate.pop(field)
            with self.subTest(field=field), self.assertRaises(
                prompt_cache.PromptCacheContractError
            ):
                prompt_cache.build_ordered_prompt_identity(candidate)
        candidate = _manifest()
        candidate["product_version"] = "V2.39"
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(candidate)

    def test_segment_provenance_and_inclusion_fields_are_required(self) -> None:
        required = (
            "source_type",
            "source_ref",
            "content_sha256",
            "byte_count",
            "token_count",
            "token_count_status",
            "inclusion_reason",
            "inclusion_state",
            "redaction_state",
        )
        for field in required:
            candidate = _manifest()
            candidate["segments"][1].pop(field)  # type: ignore[index,union-attr]
            with self.subTest(field=field), self.assertRaises(
                prompt_cache.PromptCacheContractError
            ):
                prompt_cache.build_ordered_prompt_identity(candidate)

    def test_raw_content_and_invalid_segment_order_fail_closed(self) -> None:
        raw = _manifest()
        raw["segments"][0]["content"] = "must-not-persist"  # type: ignore[index]
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(raw)

        stable_after_dynamic = _manifest()
        segments = stable_after_dynamic["segments"]
        segments[1], segments[2] = segments[2], segments[1]  # type: ignore[index]
        for index, segment in enumerate(segments):  # type: ignore[union-attr]
            segment["order"] = index
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(stable_after_dynamic)

        platform_after_stable = _manifest()
        segments = platform_after_stable["segments"]
        segments[0], segments[1] = segments[1], segments[0]  # type: ignore[index]
        for index, segment in enumerate(segments):  # type: ignore[union-attr]
            segment["order"] = index
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(platform_after_stable)

    def test_manifest_and_segment_schemas_are_closed(self) -> None:
        top_level_raw = _manifest()
        top_level_raw["raw_prompt"] = "must-not-persist"
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(top_level_raw)

        nested_raw = _manifest()
        nested_raw["segments"][0]["payload"] = {  # type: ignore[index]
            "content": "must-not-persist"
        }
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(nested_raw)

        for index, source_ref in (
            (1, "sk-live-secret-value"),
            (2, "redacted:sk-live-secret-value"),
            (2, "raw-user-request"),
        ):
            unsafe_ref = _manifest()
            unsafe_ref["segments"][index]["source_ref"] = source_ref  # type: ignore[index]
            with self.subTest(source_ref=source_ref), self.assertRaises(
                prompt_cache.PromptCacheContractError
            ):
                prompt_cache.build_ordered_prompt_identity(unsafe_ref)

    def test_source_type_cannot_relabel_dynamic_content_as_stable(self) -> None:
        cases = (
            (0, "user"),
            (0, "tool"),
            (1, "user"),
            (1, "tool"),
            (2, "host"),
            (2, "provider_adapter"),
        )
        for index, source_type in cases:
            candidate = _manifest()
            candidate["segments"][index]["source_type"] = source_type  # type: ignore[index]
            candidate["segments"][index]["source_ref"] = (  # type: ignore[index]
                "redacted:fixture"
                if source_type in {"user", "tool"}
                else f"sha256:{'a' * 64}"
            )
            with self.subTest(index=index, source_type=source_type), self.assertRaisesRegex(
                prompt_cache.PromptCacheContractError,
                "E_ORDERED_PROMPT_MANIFEST_SOURCE_CLASS",
            ):
                prompt_cache.build_ordered_prompt_identity(candidate)

    def test_status_scope_missing_and_counts_are_a_closed_contract(self) -> None:
        invalid_combinations = (
            ("available", "partial", ["tool_results"]),
            ("partial", "complete", []),
            ("partial", "partial", []),
            ("available", "complete", ["tool_results"]),
        )
        for status, scope, missing in invalid_combinations:
            candidate = _manifest()
            candidate["manifest_status"] = status
            candidate["digest_scope"] = scope
            candidate["missing_segment_classes"] = missing
            with self.subTest(status=status, scope=scope), self.assertRaises(
                prompt_cache.PromptCacheContractError
            ):
                prompt_cache.build_ordered_prompt_identity(candidate)

        for missing in (
            ["tool_results", "tool_results"],
            ["unknown_segment_class"],
        ):
            candidate = _manifest()
            candidate["manifest_status"] = "partial"
            candidate["digest_scope"] = "partial"
            candidate["missing_segment_classes"] = missing
            with self.assertRaises(prompt_cache.PromptCacheContractError):
                prompt_cache.build_ordered_prompt_identity(candidate)

        bad_count = _manifest()
        bad_count["stable_segment_count"] = 2
        with self.assertRaises(prompt_cache.PromptCacheContractError):
            prompt_cache.build_ordered_prompt_identity(bad_count)

    def test_route_manifest_loader_rejects_nested_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "references" / "prompt-cache-manifest.json").write_text(
                """{
  "schema_version": "goal-teams-prompt-cache-v2.38",
  "schema_version": "goal-teams-prompt-cache-v2.38",
  "budget_policy": {},
  "routes": {}
}
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                prompt_cache.PromptCacheContractError,
                "E_PROMPT_MANIFEST_DUPLICATE_KEY",
            ):
                prompt_cache.load_prompt_manifest(root)

    def test_dynamic_changes_runtime_but_not_stable_prefix(self) -> None:
        baseline_manifest = _manifest()
        changed_manifest = copy.deepcopy(baseline_manifest)
        changed_manifest["segments"][2]["content_sha256"] = "f" * 64  # type: ignore[index]
        baseline = prompt_cache.build_ordered_prompt_identity(baseline_manifest)
        changed = prompt_cache.build_ordered_prompt_identity(changed_manifest)
        self.assertEqual(
            baseline["stable_prefix_digest"], changed["stable_prefix_digest"]
        )
        self.assertNotEqual(
            baseline["runtime_prompt_digest"], changed["runtime_prompt_digest"]
        )

    def test_omitted_segments_bind_manifest_but_not_effective_runtime(self) -> None:
        baseline_manifest = _manifest()
        omitted_manifest = copy.deepcopy(baseline_manifest)
        omitted_manifest["segments"][2]["inclusion_state"] = "omitted"  # type: ignore[index]
        baseline = prompt_cache.build_ordered_prompt_identity(baseline_manifest)
        omitted = prompt_cache.build_ordered_prompt_identity(omitted_manifest)
        self.assertNotEqual(
            baseline["ordered_prompt_manifest_sha256"],
            omitted["ordered_prompt_manifest_sha256"],
        )
        self.assertNotEqual(
            baseline["runtime_prompt_digest"], omitted["runtime_prompt_digest"]
        )
        self.assertEqual(
            baseline["stable_prefix_digest"], omitted["stable_prefix_digest"]
        )
        self.assertEqual(baseline["effective_segment_count"], 3)
        self.assertEqual(omitted["effective_segment_count"], 2)

    def test_insert_move_or_modify_omitted_segment_keeps_effective_digests(self) -> None:
        baseline = prompt_cache.build_ordered_prompt_identity(_manifest())

        with_omitted = _manifest()
        omitted_segment = _segment(1, "omitted", "dynamic")
        omitted_segment["inclusion_state"] = "omitted"
        with_omitted["segments"].insert(1, omitted_segment)  # type: ignore[union-attr]
        with_omitted["dynamic_segment_count"] = 2
        for index, segment in enumerate(with_omitted["segments"]):  # type: ignore[union-attr]
            segment["order"] = index
        inserted = prompt_cache.build_ordered_prompt_identity(with_omitted)

        modified_manifest = copy.deepcopy(with_omitted)
        modified_manifest["segments"][1]["content_sha256"] = "e" * 64  # type: ignore[index]
        modified = prompt_cache.build_ordered_prompt_identity(modified_manifest)

        moved_manifest = copy.deepcopy(with_omitted)
        moved = moved_manifest["segments"].pop(1)  # type: ignore[union-attr]
        moved_manifest["segments"].append(moved)  # type: ignore[union-attr]
        for index, segment in enumerate(moved_manifest["segments"]):  # type: ignore[union-attr]
            segment["order"] = index
        moved_identity = prompt_cache.build_ordered_prompt_identity(moved_manifest)

        for candidate in (inserted, modified, moved_identity):
            self.assertEqual(
                candidate["stable_prefix_digest"], baseline["stable_prefix_digest"]
            )
            self.assertEqual(
                candidate["runtime_prompt_digest"], baseline["runtime_prompt_digest"]
            )
            self.assertEqual(candidate["effective_segment_count"], 3)
        self.assertNotEqual(
            inserted["ordered_prompt_manifest_sha256"],
            modified["ordered_prompt_manifest_sha256"],
        )
        self.assertNotEqual(
            inserted["ordered_prompt_manifest_sha256"],
            moved_identity["ordered_prompt_manifest_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
