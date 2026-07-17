"""Independent V2.39 Cache Evidence contracts (Architecture Revision 2).

No test calls a provider.  Production trust, authorization and raw Evidence
must originate from package-bound, data-only receipts; caller callbacks and
plain dictionaries are adversarial inputs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from tests.v23.common import ROOT


FIXTURES = ROOT / "tests" / "v23" / "fixtures" / "v239" / "cache"
PROMPT_CACHE_PATH = ROOT / "scripts" / "v23" / "prompt_cache.py"
CACHE_PROBE_PATH = ROOT / "scripts" / "v23" / "cache_probe.py"
TRUST_POLICY_PATH = ROOT / "references" / "prompt-cache-trust-policy.json"
PROVIDER_LIKE_MARKER = "sk-" + "proj-EXAMPLESECRET"
PRIVATE_HOME_MARKER = "/Users/" + "private"


def _load_optional(name: str, path: Path):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prompt_cache = _load_optional("goalteams_v239_prompt_cache_test", PROMPT_CACHE_PATH)
cache_probe = _load_optional("goalteams_v239_cache_probe_test", CACHE_PROBE_PATH)


def _json_fixture(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"fixture {name} must be an object")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _walk_json(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            yield child_path, child
            yield from _walk_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _raw_receipt_fixture(root: Path) -> tuple[Path, bytes]:
    raw = (
        b'{"type":"turn.completed","event_id":"turn-1","usage":'
        b'{"input_tokens":100,"cached_input_tokens":60}}\n'
    )
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "events.jsonl"
    raw_path.write_bytes(raw)
    receipt = {
        "schema_version": "goal-teams-raw-usage-receipt-v2.39",
        "raw_path": "raw/events.jsonl",
        "byte_size": len(raw),
        "sha256": _sha256_bytes(raw),
        "adapter_id": "synthetic-usage-adapter",
        "adapter_version": "1",
        "event_schema": "codex-turn-completed-v1",
        "capture_invocation_id": "CAPTURE-001",
        "capture_sequence": 1,
        "exclusive_create": True,
        "finalize_state": "finalized",
        "adapter_policy_sha256": "a" * 64,
        "evidence_origin": "synthetic_fixture",
        "evidence_eligible": False,
    }
    receipt_path = raw_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return receipt_path, raw


class V239CacheEvidenceContractTests(unittest.TestCase):
    def api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(prompt_cache, "scripts/v23/prompt_cache.py is required")
        value = getattr(prompt_cache, name, None)
        self.assertTrue(callable(value), f"missing public API prompt_cache.{name}")
        return value

    def probe_api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(cache_probe, "scripts/v23/cache_probe.py is required")
        value = getattr(cache_probe, name, None)
        self.assertTrue(callable(value), f"missing public API cache_probe.{name}")
        return value

    def receipt(self) -> dict[str, Any]:
        return self.api("build_host_capability_receipt")(
            _json_fixture("host-capability-input.json")
        )

    def identity(self, adapter: dict[str, Any] | None = None) -> dict[str, Any]:
        receipt = self.receipt()
        manifest = _json_fixture("partial-ordered-manifest.json")
        manifest["capability_receipt_sha256"] = receipt["receipt_sha256"]
        if adapter is not None:
            manifest["request_binding_id"] = adapter["capture_invocation_id"]
            manifest["host_adapter_identity_sha256"] = adapter[
                "adapter_policy_sha256"
            ]
        return self.api("build_ordered_prompt_identity_v239")(manifest, receipt)

    def plan(self) -> dict[str, Any]:
        return self.probe_api("build_live_probe_plan")(
            {"layout_id": "current", "runtime_prompt_digest": "a" * 64},
            {"layout_id": "candidate", "runtime_prompt_digest": "b" * 64},
            {
                "product_version": "V2.39",
                "model": "fixture-model",
                "config_sha256": "c" * 64,
                "scorer_sha256": "d" * 64,
                "harness_sha256": "e" * 64,
            },
            {
                "adapter_id": "fixture-adapter",
                "repeats": 1,
                "budget": {"max_invocations": 16, "max_cost_usd": 0},
            },
        )

    def test_required_cache_public_apis_exist(self) -> None:
        for name in (
            "build_host_capability_receipt",
            "build_ordered_prompt_identity_v239",
            "load_production_cache_policy",
            "verify_host_attestation",
            "verify_live_authorization",
            "build_cache_status_axes",
            "persist_usage_events",
            "normalize_usage_events",
            "aggregate_normalized_events",
            "open_v238_cache_artifact",
            "replay_v238_cache_record",
        ):
            with self.subTest(name=name):
                self.api(name)
        for name in ("build_live_probe_plan", "execute_live_probe"):
            with self.subTest(name=name):
                self.probe_api(name)

    def test_capability_receipt_is_closed_and_explicit(self) -> None:
        receipt = self.receipt()
        self.assertEqual(
            receipt["schema_version"], "goal-teams-host-capability-receipt-v2.39"
        )
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            set(receipt["capabilities"]),
            {
                "final_request_boundary",
                "effective_config_attestation",
                "provider_usage_events",
                "cache_namespace_control",
                "request_hit_semantics",
            },
        )
        invalid = _json_fixture("host-capability-input.json")
        invalid["caller_says_supported"] = True
        with self.assertRaisesRegex(Exception, "E_HOST_CAPABILITY_UNKNOWN_FIELD"):
            self.api("build_host_capability_receipt")(invalid)

    def test_receipt_metadata_rejects_paths_and_secret_markers(self) -> None:
        build_capability = self.api("build_host_capability_receipt")
        for field, value in (
            ("receipt_id", PROVIDER_LIKE_MARKER),
            ("host_adapter_id", PRIVATE_HOME_MARKER + "/adapter"),
            ("host_adapter_version", "file:///private/version"),
        ):
            payload = _json_fixture("host-capability-input.json")
            payload[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                Exception, "E_HOST_CAPABILITY_SCHEMA"
            ):
                build_capability(payload)

        build_adapter = self.api("build_test_only_adapter_receipt")
        for kwargs in (
            {"adapter_id": PRIVATE_HOME_MARKER + "/adapter"},
            {"adapter_version": "file:///private/version"},
            {"capture_invocation_id": PROVIDER_LIKE_MARKER},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                Exception, "E_CACHE_ADAPTER_TEST_RECEIPT"
            ):
                build_adapter(**kwargs)

    def test_partial_manifest_never_emits_stable_or_runtime_digest(self) -> None:
        receipt = self.receipt()
        manifest = _json_fixture("partial-ordered-manifest.json")
        manifest["capability_receipt_sha256"] = receipt["receipt_sha256"]
        identity = self.api("build_ordered_prompt_identity_v239")(manifest, receipt)
        self.assertEqual(identity["manifest_status"], "partial")
        self.assertIsNone(identity["stable_prefix_digest"])
        self.assertIsNone(identity["runtime_prompt_digest"])
        self.assertRegex(
            identity["ordered_prompt_manifest_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            set(identity["missing_segment_classes"]),
            {"provider_adapter_injections", "tool_results"},
        )

    def test_canonical_trust_policy_is_data_only_and_has_no_executable_fields(self) -> None:
        self.assertTrue(
            TRUST_POLICY_PATH.is_file(),
            "references/prompt-cache-trust-policy.json is required",
        )
        policy = json.loads(TRUST_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            policy["schema_version"], "goal-teams-prompt-cache-trust-policy-v2.39"
        )
        forbidden = {
            "callback",
            "module",
            "module_path",
            "import",
            "shell",
            "command",
            "executable",
            "executable_path",
            "trust_class",
        }
        for path, value in _walk_json(policy):
            with self.subTest(path=path):
                self.assertNotIn(path.rsplit(".", 1)[-1], forbidden)
                self.assertFalse(callable(value))

    def test_production_policy_loader_requires_package_and_checker_binding(self) -> None:
        fake_identity = {
            "schema_version": "goal-teams-package-identity-v1",
            "product_version": "V2.39",
            "package_tree_digest": "a" * 64,
            "policy_sha256": "b" * 64,
            "loader_sha256": "c" * 64,
            "checker_sha256": "d" * 64,
            "caller_declared": True,
        }
        with self.assertRaisesRegex(
            Exception,
            "E_CACHE_POLICY_(PACKAGE_BINDING|CHECKER_BINDING)",
        ):
            self.api("load_production_cache_policy")(ROOT, fake_identity)

    def test_production_attestation_rejects_caller_registry_and_callback(self) -> None:
        verify = self.api("verify_host_attestation")
        callback_registry = {"verifiers": {"x": {"verify": lambda value: True}}}
        with self.assertRaisesRegex(Exception, "E_CACHE_ATTESTATION_CALLER_REGISTRY"):
            verify(
                {"schema_version": "goal-teams-host-attestation-v2.39"},
                production_policy_receipt={"caller_registry": callback_registry},
                registry=callback_registry,
            )

    def test_plain_authorization_dict_is_not_authorized(self) -> None:
        result = self.api("verify_live_authorization")(
            json.dumps({"authorized": True}).encode("utf-8"),
            production_policy_receipt={"caller_declared": True},
            replay_state={},
        )
        self.assertIn(result["status"], {"not_authorized", "invalid"})
        self.assertNotEqual(result["status"], "authorized")
        self.assertIn(
            result["error_code"],
            {"E_CACHE_AUTH_ISSUER", "E_CACHE_AUTH_PROOF", "E_CACHE_POLICY_PACKAGE_BINDING"},
        )

    def test_four_status_axes_are_independent_and_closed(self) -> None:
        axes = self.api("build_cache_status_axes")(
            structural_delivery_state="passed",
            host_integration_state="unavailable",
            live_cache_validation_state="not_authorized",
            request_hit_rate_support_state="unsupported",
        )
        self.assertEqual(axes["schema_version"], "goal-teams-cache-status-v2.39")
        self.assertEqual(axes["claim_scope"], "structural_only")
        self.assertEqual(axes["host_integration_state"], "unavailable")
        with self.assertRaisesRegex(Exception, "E_CACHE_STATUS_AXIS"):
            self.api("build_cache_status_axes")(
                structural_delivery_state="passed",
                host_integration_state="trusted",
                live_cache_validation_state="optimized",
                request_hit_rate_support_state="supported",
            )

    def test_direct_jsonl_string_is_diagnostic_non_evidence(self) -> None:
        events = json.dumps(
            {
                "type": "turn.completed",
                "event_id": "turn-1",
                "usage": {"input_tokens": 100, "cached_input_tokens": 80},
            }
        )
        legacy = prompt_cache.aggregate_usage_events(events)
        self.assertFalse(legacy["evidence_eligible"])
        self.assertEqual(legacy["evidence_class"], "diagnostic_non_evidence")
        self.assertIsNone(legacy["request_hit_rate"])

        with tempfile.TemporaryDirectory() as td:
            direct = self.api("persist_usage_events")(
                events,
                Path(td),
                {"caller_declared": True},
            )
        self.assertFalse(direct["evidence_eligible"])
        self.assertEqual(direct["evidence_class"], "diagnostic_non_evidence")

    def test_raw_receipt_loader_recomputes_finalized_bytes_and_hash(self) -> None:
        loader = self.api("load_raw_usage_receipt")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt_path, raw = _raw_receipt_fixture(root)
            receipt = loader(receipt_path)
            self.assertEqual(receipt["finalize_state"], "finalized")
            self.assertEqual(receipt["sha256"], _sha256_bytes(raw))
            self.assertEqual(receipt["byte_size"], len(raw))
            self.assertNotIn(str(root), json.dumps(receipt, ensure_ascii=False))

    def test_raw_receipt_rejects_symlink_and_hash_drift(self) -> None:
        loader = self.api("load_raw_usage_receipt")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt_path, _raw = _raw_receipt_fixture(root)
            raw_path = root / "raw" / "events.jsonl"
            raw_path.unlink()
            raw_path.symlink_to(FIXTURES / "v238-record.json")
            with self.assertRaisesRegex(Exception, "E_CACHE_RAW_SYMLINK"):
                loader(receipt_path)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt_path, _raw = _raw_receipt_fixture(root)
            (root / "raw" / "events.jsonl").write_bytes(b"drift\n")
            with self.assertRaisesRegex(Exception, "E_CACHE_RAW_HASH_DRIFT"):
                loader(receipt_path)

    def test_raw_receipt_loader_rejects_sensitive_adapter_metadata(self) -> None:
        loader = self.api("load_raw_usage_receipt")
        cases = (
            ("adapter_id", PRIVATE_HOME_MARKER + "/adapter"),
            ("adapter_version", "file:///private/version"),
            ("capture_invocation_id", PROVIDER_LIKE_MARKER),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                receipt_path, _raw = _raw_receipt_fixture(root)
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt[field] = value
                receipt_path.write_text(
                    json.dumps(
                        receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(Exception, "E_CACHE_RAW_RECEIPT_SCHEMA"):
                    loader(receipt_path)

    def test_usage_persistence_rejects_all_absolute_path_families(self) -> None:
        persist = self.api("persist_usage_events")
        receipt = self.api("build_test_only_adapter_receipt")()
        values = (
            "/etc/passwd",
            "/tmp/private.log",
            "/var/run/service.sock",
            "C:\\" + "\\Users\\person\\secret.txt",
            r"D:/work/private.txt",
            r"\\server\\share\\private.txt",
            "file:///etc/passwd",
        )
        for index, value in enumerate(values, start=1):
            event = {
                "type": "turn.completed",
                "event_id": f"turn-{index}",
                "cwd": value,
                "usage": {"input_tokens": 10, "cached_input_tokens": 5},
            }
            raw = (json.dumps(event) + "\n").encode("utf-8")
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(Exception, "E_CACHE_RAW_SECURITY"):
                    persist(io.BytesIO(raw), Path(td), receipt)

    def test_usage_persistence_is_closed_usage_only_and_rejects_secret_fields(self) -> None:
        persist = self.api("persist_usage_events")
        receipt = self.api("build_test_only_adapter_receipt")()
        cases = (
            {"data": "arbitrary prompt text"},
            {"input": "hidden request"},
            {"access_token": "dummy-fixture-opaque-access"},
            {"client_secret": "dummy-fixture-opaque-client"},
            {"private_key": "dummy-fixture-private-key"},
            {"cookie": "dummy-fixture-session-abc"},
            {"aws_access_key_id": "AKIAEXAMPLEVALUE"},
        )
        for index, extra in enumerate(cases, start=1):
            event = {
                "type": "turn.completed",
                "event_id": f"turn-secret-{index}",
                "usage": {"input_tokens": 10, "cached_input_tokens": 5},
                **extra,
            }
            raw = (json.dumps(event) + "\n").encode("utf-8")
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(Exception, "E_CACHE_RAW_SECURITY"):
                    persist(io.BytesIO(raw), Path(td), receipt)

        nested = {
            "type": "turn.completed",
            "event_id": "turn-nested-secret",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 5,
                "session_token": "dummy-fixture-opaque-session",
            },
        }
        with tempfile.TemporaryDirectory() as td, self.assertRaisesRegex(
            Exception, "E_CACHE_RAW_SECURITY"
        ):
            persist(
                io.BytesIO((json.dumps(nested) + "\n").encode("utf-8")),
                Path(td),
                receipt,
            )

    def test_usage_persistence_validates_every_token_field_before_disk(self) -> None:
        persist = self.api("persist_usage_events")
        receipt = self.api("build_test_only_adapter_receipt")()
        invalid_usage = (
            {"input_tokens": 10, "cached_input_tokens": 11},
            {"input_tokens": True, "cached_input_tokens": 1},
            {"input_tokens": 10, "cached_input_tokens": -1},
            {
                "input_tokens": 10,
                "cached_input_tokens": 5,
                "output_tokens": "private user content without marker",
            },
            {
                "input_tokens": 10,
                "cached_input_tokens": 5,
                "reasoning_output_tokens": False,
            },
        )
        for index, usage in enumerate(invalid_usage, start=1):
            event = {
                "type": "turn.completed",
                "event_id": f"turn-invalid-usage-{index}",
                "usage": usage,
            }
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(Exception, "E_CACHE_USAGE_SCHEMA"):
                    persist(
                        io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                        Path(td),
                        receipt,
                    )
                self.assertFalse((Path(td) / "raw").exists())

    def test_normalize_and_aggregate_reject_forged_receipts(self) -> None:
        forged_raw = {
            "schema_version": "goal-teams-raw-usage-receipt-v2.39",
            "raw_path": "raw/events.jsonl",
            "sha256": "a" * 64,
            "finalize_state": "finalized",
            "caller_declared": True,
        }
        with self.assertRaisesRegex(Exception, "E_CACHE_RAW_RECEIPT_UNTRUSTED"):
            self.api("normalize_usage_events")(forged_raw, {"caller_declared": True})
        with self.assertRaisesRegex(Exception, "E_CACHE_RAW_RECEIPT_UNTRUSTED"):
            self.api("aggregate_normalized_events")(
                {"schema_version": "goal-teams-normalized-usage-receipt-v2.39"},
                {"runtime_prompt_digest": "a" * 64},
            )

    def test_normalized_receipt_mutation_cannot_upgrade_synthetic_evidence(self) -> None:
        persist = self.api("persist_usage_events")
        normalize = self.api("normalize_usage_events")
        aggregate = self.api("aggregate_normalized_events")
        adapter = self.api("build_test_only_adapter_receipt")()
        event = {
            "type": "turn.completed",
            "event_id": "turn-immutable",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        with tempfile.TemporaryDirectory() as td:
            raw = persist(
                io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                Path(td),
                adapter,
            )
            normalized = normalize(raw, adapter)
            normalized["evidence_origin"] = "host_runtime"
            normalized["evidence_eligible"] = True
            with self.assertRaisesRegex(
                Exception, "E_CACHE_NORMALIZED_RECEIPT_BINDING"
            ):
                aggregate(normalized, self.identity(adapter))

    def test_bound_receipts_reject_synchronized_file_and_public_field_mutation(self) -> None:
        persist = self.api("persist_usage_events")
        normalize = self.api("normalize_usage_events")
        aggregate = self.api("aggregate_normalized_events")
        adapter = self.api("build_test_only_adapter_receipt")()
        event = {
            "type": "turn.completed",
            "event_id": "turn-bound",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = persist(
                io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                root,
                adapter,
            )
            tampered_event = {
                **event,
                "usage": {"input_tokens": 999, "cached_input_tokens": 999},
            }
            tampered_raw = (json.dumps(tampered_event) + "\n").encode("utf-8")
            (root / raw["raw_path"]).write_bytes(tampered_raw)
            raw["byte_size"] = len(tampered_raw)
            raw["sha256"] = _sha256_bytes(tampered_raw)
            with self.assertRaisesRegex(Exception, "E_CACHE_RAW_RECEIPT_BINDING"):
                normalize(raw, adapter)

        adapter = self.api("build_test_only_adapter_receipt")()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = persist(
                io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                root,
                adapter,
            )
            normalized = normalize(raw, adapter)
            normalized_path = root / normalized["normalized_path"]
            payload = json.loads(normalized_path.read_text(encoding="utf-8"))
            payload["input_tokens"] = 1234
            payload["cached_input_tokens"] = 1234
            payload["uncached_input_tokens"] = 0
            tampered = (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            normalized_path.write_bytes(tampered)
            normalized["byte_size"] = len(tampered)
            normalized["sha256"] = _sha256_bytes(tampered)
            with self.assertRaisesRegex(
                Exception, "E_CACHE_NORMALIZED_RECEIPT_BINDING"
            ):
                aggregate(normalized, self.identity(adapter))

    def test_adapter_receipt_mutation_is_rejected_before_persistence(self) -> None:
        adapter = self.api("build_test_only_adapter_receipt")()
        adapter["adapter_id"] = "tampered-adapter"
        event = {
            "type": "turn.completed",
            "event_id": "turn-adapter-binding",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        with tempfile.TemporaryDirectory() as td, self.assertRaisesRegex(
            Exception, "E_CACHE_ADAPTER_RECEIPT_BINDING"
        ):
            self.api("persist_usage_events")(
                io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                Path(td),
                adapter,
            )

    def test_evidence_subdirectory_symlinks_cannot_escape_before_write(self) -> None:
        persist = self.api("persist_usage_events")
        normalize = self.api("normalize_usage_events")
        adapter = self.api("build_test_only_adapter_receipt")()
        event = {
            "type": "turn.completed",
            "event_id": "turn-no-escape",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        raw_bytes = (json.dumps(event) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "root"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "raw").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(Exception, "E_CACHE_RAW_OUTPUT_ROOT"):
                persist(io.BytesIO(raw_bytes), root, adapter)
            self.assertEqual(list(outside.iterdir()), [])

        adapter = self.api("build_test_only_adapter_receipt")()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "root"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            raw = persist(io.BytesIO(raw_bytes), root, adapter)
            (root / "normalized").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(Exception, "E_CACHE_RAW_OUTPUT_ROOT"):
                normalize(raw, adapter)
            self.assertEqual(list(outside.iterdir()), [])

    def test_aggregate_requires_minted_matching_runtime_identity(self) -> None:
        persist = self.api("persist_usage_events")
        normalize = self.api("normalize_usage_events")
        aggregate = self.api("aggregate_normalized_events")
        adapter = self.api("build_test_only_adapter_receipt")()
        event = {
            "type": "turn.completed",
            "event_id": "turn-identity-binding",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        with tempfile.TemporaryDirectory() as td:
            raw = persist(
                io.BytesIO((json.dumps(event) + "\n").encode("utf-8")),
                Path(td),
                adapter,
            )
            normalized = normalize(raw, adapter)
            for forged in (
                {},
                {"product_version": "V2.38", "runtime_prompt_digest": None},
                {"secret": "dummy-fixture-raw-prompt"},
            ):
                with self.subTest(forged=forged), self.assertRaisesRegex(
                    Exception, "E_CACHE_METRICS_IDENTITY"
                ):
                    aggregate(normalized, forged)

            wrong_adapter = self.api("build_test_only_adapter_receipt")(
                adapter_id="other-synthetic-adapter",
                capture_invocation_id="other-request-binding",
            )
            with self.assertRaisesRegex(
                Exception, "E_CACHE_METRICS_IDENTITY_BINDING"
            ):
                aggregate(normalized, self.identity(wrong_adapter))

            identity = self.identity(adapter)
            identity["product_version"] = "V2.38"
            with self.assertRaisesRegex(Exception, "E_CACHE_METRICS_IDENTITY"):
                aggregate(normalized, identity)

    def test_usage_event_ids_are_deduplicated_and_conflicts_are_degraded(self) -> None:
        persist = self.api("persist_usage_events")
        normalize = self.api("normalize_usage_events")
        aggregate = self.api("aggregate_normalized_events")

        def run(events: list[dict[str, Any]]) -> dict[str, Any]:
            adapter = self.api("build_test_only_adapter_receipt")()
            raw_bytes = b"".join(
                (json.dumps(event) + "\n").encode("utf-8") for event in events
            )
            with tempfile.TemporaryDirectory() as td:
                raw = persist(io.BytesIO(raw_bytes), Path(td), adapter)
                normalized = normalize(raw, adapter)
                return aggregate(normalized, self.identity(adapter))

        first = {
            "type": "turn.completed",
            "event_id": "same",
            "usage": {"input_tokens": 10, "cached_input_tokens": 5},
        }
        duplicate = run([first, dict(first)])
        self.assertEqual(duplicate["sample_count"], 1)
        self.assertEqual(duplicate["total_input_tokens"], 10)
        self.assertEqual(duplicate["duplicate_events"], 1)
        self.assertEqual(duplicate["conflicting_events"], 0)
        self.assertEqual(duplicate["duplicate_detection_state"], "complete")

        conflict = {
            **first,
            "usage": {"input_tokens": 20, "cached_input_tokens": 5},
        }
        conflicted = run([first, conflict])
        self.assertEqual(conflicted["sample_count"], 0)
        self.assertEqual(conflicted["total_input_tokens"], 0)
        self.assertEqual(conflicted["conflicting_events"], 1)
        self.assertEqual(conflicted["duplicate_detection_state"], "conflicted")
        self.assertEqual(conflicted["usage_status"], "partial")
        self.assertEqual(conflicted["telemetry_coverage"], 0.0)

    def test_v238_artifact_loader_binds_original_bytes_and_replay_is_read_only(self) -> None:
        open_artifact = self.api("open_v238_cache_artifact")
        replay_record = self.api("replay_v238_cache_record")
        source_bytes = (FIXTURES / "v238-record.json").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "record.json"
            source.write_bytes(source_bytes)
            receipt = open_artifact(source, _sha256_bytes(source_bytes), root)
            self.assertEqual(
                receipt["schema_version"],
                "goal-teams-v238-source-artifact-receipt-v1",
            )
            self.assertEqual(receipt["source_record_sha256"], _sha256_bytes(source_bytes))
            self.assertEqual(receipt["source_artifact_ref"], "record.json")
            self.assertTrue(receipt["read_only"])
            replay = replay_record(receipt)
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(replay["source_record_sha256"], _sha256_bytes(source_bytes))
            self.assertEqual(replay["live_cache_validation_state"], "unavailable")
            self.assertFalse(replay["evidence_origin"] == "parsed_dict")
            self.assertNotIn("legacy_record", replay)
            self.assertEqual(replay["evidence_scope"], "source_bytes_only")

    def test_v238_receipt_and_file_synchronized_mutation_is_rejected(self) -> None:
        open_artifact = self.api("open_v238_cache_artifact")
        replay_record = self.api("replay_v238_cache_record")
        source_bytes = (FIXTURES / "v238-record.json").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "record.json"
            source.write_bytes(source_bytes)
            receipt = open_artifact(source, _sha256_bytes(source_bytes), root)
            tampered = json.loads(source_bytes)
            tampered["identity_status"] = "tampered"
            tampered_bytes = json.dumps(tampered, sort_keys=True).encode("utf-8")
            source.write_bytes(tampered_bytes)
            receipt["size"] = len(tampered_bytes)
            receipt["source_record_sha256"] = _sha256_bytes(tampered_bytes)
            receipt["source_artifact_ref"] = "forged.json"
            with self.assertRaisesRegex(Exception, "E_CACHE_REPLAY_SOURCE_TYPE"):
                replay_record(receipt)

    def test_v238_replay_requires_exact_schema_and_omits_historical_payload(self) -> None:
        open_artifact = self.api("open_v238_cache_artifact")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "record.json"
            for payload in (
                {"schema_version": "attacker-v2.38"},
                {
                    "schema_version": "goal-teams-cache-identity-v2.38-evil",
                    "raw_prompt": PROVIDER_LIKE_MARKER + " " + PRIVATE_HOME_MARKER,
                },
            ):
                raw = json.dumps(payload).encode("utf-8")
                source.write_bytes(raw)
                with self.subTest(schema=payload["schema_version"]), self.assertRaisesRegex(
                    Exception, "E_CACHE_REPLAY_SOURCE_SCHEMA"
                ):
                    open_artifact(source, _sha256_bytes(raw), root)

            historical = {
                "schema_version": "goal-teams-cache-identity-v2.38",
                "product_version": "V2.38",
                "policy_profile": "goal-teams-core-v2.5",
                "gate_profile": "full",
                "agent_identity": {"agent_type": "goal_backend"},
                "route_identity": {"route_id": "benchmark"},
                "model_identity": {"status": "bound", "model": "fixture"},
                "adapter_identity": {"adapter_type": "codex"},
                "parser_identity": {"parser_version": "v1"},
                "digest_identity": {"runtime_prompt_digest": "a" * 64},
                "observer_telemetry_verification": {"status": "complete"},
                "identity_sha256": None,
                "partial_identity_sha256": "b" * 64,
                "identity_status": "incomplete",
                "missing_identity_fields": ["effective_config_verification"],
                "cache_analytics_status": "unsupported",
                "cache_analytics_reason": "effective_config_verification_incomplete",
            }
            raw = json.dumps(historical).encode("utf-8")
            source.write_bytes(raw)
            receipt = open_artifact(source, _sha256_bytes(raw), root)
            replay = self.api("replay_v238_cache_record")(receipt)
            self.assertTrue(replay["evidence_eligible"])
            self.assertEqual(replay["semantic_validation_state"], "unavailable")
            self.assertNotIn("historical", json.dumps(replay))

    def test_v238_dict_replay_is_diagnostic_only_and_cannot_be_evidence(self) -> None:
        with self.assertRaisesRegex(Exception, "E_CACHE_REPLAY_SOURCE_TYPE"):
            self.api("replay_v238_cache_record")(_json_fixture("v238-record.json"))

    def test_v238_loader_rejects_wrong_hash_symlink_and_root_escape(self) -> None:
        open_artifact = self.api("open_v238_cache_artifact")
        source_bytes = (FIXTURES / "v238-record.json").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "allowed"
            root.mkdir()
            source = root / "record.json"
            source.write_bytes(source_bytes)
            with self.assertRaisesRegex(Exception, "E_CACHE_REPLAY_SOURCE_HASH"):
                open_artifact(source, "0" * 64, root)
            linked = root / "linked.json"
            linked.symlink_to(source)
            with self.assertRaisesRegex(Exception, "E_CACHE_REPLAY_SOURCE_PATH"):
                open_artifact(linked, _sha256_bytes(source_bytes), root)
            outside = Path(td) / "outside.json"
            outside.write_bytes(source_bytes)
            with self.assertRaisesRegex(Exception, "E_CACHE_REPLAY_SOURCE_PATH"):
                open_artifact(outside, _sha256_bytes(source_bytes), root)

    def test_semantically_equal_v238_files_keep_distinct_raw_hashes(self) -> None:
        open_artifact = self.api("open_v238_cache_artifact")
        compact = b'{"schema_version":"goal-teams-cache-identity-v2.38"}\n'
        spaced = b'{ "schema_version": "goal-teams-cache-identity-v2.38" }\r\n'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first.json"
            second = root / "second.json"
            first.write_bytes(compact)
            second.write_bytes(spaced)
            one = open_artifact(first, _sha256_bytes(compact), root)
            two = open_artifact(second, _sha256_bytes(spaced), root)
            self.assertNotEqual(one["source_record_sha256"], two["source_record_sha256"])

    def test_probe_plan_is_interleaved_but_production_executor_rejects_caller_objects(self) -> None:
        plan = self.plan()
        layouts = [item["layout_id"] for item in plan["invocations"]]
        for index in range(0, len(layouts), 2):
            self.assertEqual(layouts[index : index + 2], ["current", "candidate"])

        calls: list[str] = []

        def callback(_value: Any) -> None:
            calls.append("called")

        result = self.probe_api("execute_live_probe")(
            plan,
            {"authorized": True},
            {"adapters": {"fixture-adapter": {"callback": callback}}},
            Path(tempfile.gettempdir()) / "goal-teams-v239-no-provider",
        )
        self.assertEqual(result["execution_state"], "not_authorized")
        self.assertEqual(calls, [])
        self.assertNotIn("callback", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
