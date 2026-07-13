"""Focused V2.38 tests for generated stable-prefix and packet artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.v23.common import ROOT


MODULE_PATH = ROOT / "scripts" / "v23" / "prompt_compilers.py"
FIXTURES = ROOT / "tests" / "v23" / "fixtures" / "v238"


def _load_module():
    spec = importlib.util.spec_from_file_location("goalteams_v238_prompt_compilers_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


compiler = _load_module()


class V238PromptCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assignment = json.loads(
            (FIXTURES / "member-goal-packet-assignment.json").read_text(encoding="utf-8")
        )

    def test_common_source_metadata_and_expansion_are_exact_and_idempotent(self) -> None:
        contract = compiler.load_common_prefix(ROOT)
        source = (ROOT / contract["source_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), contract["common_prefix_sha256"])
        self.assertEqual(contract["common_prefix_version"], "V2.38")

        validation = compiler.validate_subagent_prefixes(ROOT)
        self.assertTrue(validation["passed"], validation)
        self.assertEqual(validation["target_count"], 18)
        self.assertEqual(validation["common_prefix_bytes"], len(source))

        first = compiler.expand_subagent_prefixes(ROOT)
        second = compiler.expand_subagent_prefixes(ROOT)
        self.assertEqual(first["outputs"], second["outputs"])
        self.assertEqual(first["changed"], [])
        for path in sorted((ROOT / "subagents").glob("goal-*.toml")):
            raw = path.read_text(encoding="utf-8")
            parsed = tomllib.loads(raw)
            self.assertIn(
                f'# common_prefix_version = "{contract["common_prefix_version"]}"', raw
            )
            self.assertIn(
                f'# common_prefix_sha256 = "{contract["common_prefix_sha256"]}"', raw
            )
            self.assertTrue(parsed["developer_instructions"].startswith(contract["text"]))

    def test_negative_fixtures_distinguish_role_before_prefix_and_drift(self) -> None:
        contract = compiler.load_common_prefix(ROOT)
        fixture = json.loads(
            (FIXTURES / "subagent-prefix-negative-cases.json").read_text(encoding="utf-8")
        )
        suffix = "你是独立的 Goal Teams fixture role。\n"
        for case in fixture["cases"]:
            with self.subTest(case_id=case["case_id"]):
                if case["mutation"] == "prepend":
                    value = case["value"] + contract["text"] + suffix
                else:
                    value = contract["text"].replace(
                        case["find"], case["replace"], 1
                    ) + suffix
                self.assertEqual(
                    compiler.validate_developer_instructions(contract["text"], value),
                    [case["expected_error"]],
                )

    def test_expander_repairs_prefix_drift_but_rejects_role_before_prefix(self) -> None:
        contract = compiler.load_common_prefix(ROOT)
        manifest = json.loads(
            (ROOT / "references" / "prompt-cache-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        manifest["artifact_compilers"]["subagent_common_prefix"]["target_count"] = 1
        source = (ROOT / contract["source_path"]).read_text(encoding="utf-8")
        suffix = "你是独立的 Goal Teams fixture role。\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "subagents").mkdir()
            (root / "references" / "prompt-cache-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            (root / contract["source_path"]).write_text(source, encoding="utf-8")
            target = root / "subagents" / "goal-fixture.toml"

            def write_target(body: str) -> None:
                target.write_text(
                    "name = \"goal_fixture\"\n"
                    f"# common_prefix_version = \"{contract['common_prefix_version']}\"\n"
                    f"# common_prefix_sha256 = \"{contract['common_prefix_sha256']}\"\n"
                    'developer_instructions = """\n'
                    + body
                    + '"""\n',
                    encoding="utf-8",
                )

            drifted = source.replace(
                "只以 current Evidence 支撑 accepted",
                "只以未经绑定的 Evidence 支撑 accepted",
                1,
            )
            write_target(drifted + suffix)
            rendered = compiler.render_subagent_target(root, target)
            self.assertTrue(tomllib.loads(rendered)["developer_instructions"].startswith(source))
            expansion = compiler.expand_subagent_prefixes(root, write=True)
            self.assertEqual(expansion["changed"], ["subagents/goal-fixture.toml"])
            self.assertTrue(
                tomllib.loads(target.read_text(encoding="utf-8"))["developer_instructions"].startswith(
                    source
                )
            )
            self.assertEqual(compiler.expand_subagent_prefixes(root)["changed"], [])

            write_target("角色先行。\n" + source + suffix)
            with self.assertRaisesRegex(
                compiler.PromptCompilerError, "E_SUBAGENT_ROLE_BEFORE_COMMON_PREFIX"
            ):
                compiler.expand_subagent_prefixes(root, write=True)

    def test_packet_serializer_hashes_real_stable_dynamic_and_combined_bytes(self) -> None:
        first = compiler.serialize_member_goal_packet(ROOT, self.assignment)
        second = compiler.serialize_member_goal_packet(ROOT, self.assignment)
        self.assertEqual(first, second)

        marker = "<!-- goal-teams-dynamic-tail -->"
        packet_bytes = first["packet_text"].encode("utf-8")
        marker_end = packet_bytes.index(marker.encode("utf-8")) + len(marker.encode("utf-8"))
        stable_bytes = packet_bytes[:marker_end]
        canonical = compiler.canonical_assignment(ROOT, self.assignment)
        dynamic_bytes = (
            json.dumps(
                canonical,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=False,
            )
            + "\n"
        ).encode("utf-8")

        self.assertEqual(first["stable_prefix_sha256"], hashlib.sha256(stable_bytes).hexdigest())
        self.assertEqual(
            first["dynamic_assignment_sha256"], hashlib.sha256(dynamic_bytes).hexdigest()
        )
        self.assertEqual(first["combined_packet_sha256"], hashlib.sha256(packet_bytes).hexdigest())
        self.assertEqual(first["stable_prefix_bytes"], len(stable_bytes))
        self.assertEqual(first["dynamic_assignment_bytes"], len(dynamic_bytes))
        self.assertEqual(first["combined_packet_bytes"], len(packet_bytes))
        self.assertNotIn(first["combined_packet_sha256"], first["packet_text"])
        budget_receipt = first["dynamic_budget_receipt"]
        self.assertTrue(budget_receipt["passed"])
        self.assertEqual(budget_receipt["final_action"], "accept")
        self.assertEqual(
            budget_receipt["actual"]["dynamic_assignment_bytes"],
            first["dynamic_assignment_bytes"],
        )
        manifest = json.loads(
            (ROOT / "references" / "prompt-cache-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            budget_receipt["declared"]["dynamic_packet_max_bytes"],
            manifest["budget_policy"]["dynamic_packet_max_bytes"],
        )

        changed = dict(self.assignment)
        changed["goal"] = "只改变动态目标"
        changed_result = compiler.serialize_member_goal_packet(ROOT, changed)
        self.assertEqual(first["stable_prefix_sha256"], changed_result["stable_prefix_sha256"])
        self.assertNotEqual(
            first["dynamic_assignment_sha256"], changed_result["dynamic_assignment_sha256"]
        )
        self.assertNotEqual(
            first["combined_packet_sha256"], changed_result["combined_packet_sha256"]
        )

    def test_packet_serializer_fails_closed_above_dynamic_byte_budget(self) -> None:
        oversized = dict(self.assignment)
        oversized["goal"] = "界" * 6000
        with self.assertRaisesRegex(
            compiler.PromptCompilerError, "^E_PACKET_DYNAMIC_BUDGET_EXCEEDED$"
        ) as raised:
            compiler.serialize_member_goal_packet(ROOT, oversized)
        receipt = raised.exception.receipt
        self.assertIsNotNone(receipt)
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["final_action"], "reject")
        self.assertEqual(receipt["violations"], ["E_PACKET_DYNAMIC_BUDGET_EXCEEDED"])
        self.assertGreater(
            receipt["actual"]["dynamic_assignment_bytes"],
            receipt["declared"]["dynamic_packet_max_bytes"],
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assignment_path = root / "oversized.json"
            output = root / "packet.md"
            metadata = root / "packet.json"
            assignment_path.write_text(
                json.dumps(oversized, ensure_ascii=False), encoding="utf-8"
            )
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = compiler.main(
                    [
                        "--root",
                        str(ROOT),
                        "compile-packet",
                        "--assignment",
                        str(assignment_path),
                        "--output",
                        str(output),
                        "--metadata",
                        str(metadata),
                    ]
                )
            failure = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(failure["error"], "E_PACKET_DYNAMIC_BUDGET_EXCEEDED")
            self.assertFalse(failure["dynamic_budget_receipt"]["passed"])
            self.assertFalse(output.exists())
            self.assertFalse(metadata.exists())

    def test_packet_cli_writes_bytes_and_matching_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "packet.md"
            metadata = Path(td) / "packet.json"
            with redirect_stdout(io.StringIO()):
                exit_code = compiler.main(
                    [
                        "--root",
                        str(ROOT),
                        "compile-packet",
                        "--assignment",
                        str(FIXTURES / "member-goal-packet-assignment.json"),
                        "--output",
                        str(output),
                        "--metadata",
                        str(metadata),
                    ]
                )
            self.assertEqual(exit_code, 0)
            sidecar = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(
                sidecar["combined_packet_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )
            self.assertEqual(sidecar["combined_packet_bytes"], len(output.read_bytes()))
            self.assertTrue(sidecar["dynamic_budget_receipt"]["passed"])
            self.assertEqual(
                sidecar["dynamic_budget_receipt"]["actual"]["dynamic_assignment_bytes"],
                sidecar["dynamic_assignment_bytes"],
            )

    def test_packet_cli_rejects_duplicate_keys_for_compile_and_migrate(self) -> None:
        legacy = json.loads(
            (FIXTURES / "member-goal-packet-legacy.json").read_text(encoding="utf-8")
        )
        cases = (
            (
                "compile-packet",
                "--assignment",
                self.assignment,
                "goal",
                "重复目标",
            ),
            (
                "migrate-packet",
                "--legacy",
                legacy,
                "objective",
                "重复旧目标",
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for index, (command, input_flag, value, duplicate_key, duplicate_value) in enumerate(
                cases
            ):
                with self.subTest(command=command):
                    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    duplicated = raw[:-1] + "," + json.dumps(duplicate_key) + ":" + json.dumps(
                        duplicate_value, ensure_ascii=False
                    ) + "}"
                    input_path = root / f"duplicate-{index}.json"
                    output = root / f"packet-{index}.md"
                    metadata = root / f"packet-{index}.json"
                    input_path.write_text(duplicated, encoding="utf-8")
                    stream = io.StringIO()
                    with redirect_stdout(stream):
                        exit_code = compiler.main(
                            [
                                "--root",
                                str(ROOT),
                                command,
                                input_flag,
                                str(input_path),
                                "--output",
                                str(output),
                                "--metadata",
                                str(metadata),
                            ]
                        )
                    failure = json.loads(stream.getvalue())
                    self.assertEqual(exit_code, 1)
                    self.assertEqual(failure["error"], "E_PACKET_JSON_DUPLICATE_KEY")
                    self.assertFalse(output.exists())
                    self.assertFalse(metadata.exists())

    def test_legacy_fixture_marks_old_hashes_unavailable_and_rehashes_new_bytes(self) -> None:
        legacy = json.loads(
            (FIXTURES / "member-goal-packet-legacy.json").read_text(encoding="utf-8")
        )
        first = compiler.migrate_legacy_member_goal_packet(ROOT, legacy)
        second = compiler.migrate_legacy_member_goal_packet(ROOT, legacy)
        self.assertEqual(first, second)
        self.assertEqual(first["migration_state"], "legacy_mapped")
        self.assertEqual(first["legacy_digest_status"], "legacy/unavailable")
        for key in (
            "legacy_stable_prefix_sha256",
            "legacy_dynamic_assignment_sha256",
            "legacy_combined_packet_sha256",
        ):
            self.assertIsNone(first[key])
        compiled = first["compiled"]
        for key in (
            "stable_prefix_sha256",
            "dynamic_assignment_sha256",
            "combined_packet_sha256",
        ):
            self.assertRegex(compiled[key], r"^[0-9a-f]{64}$")
        self.assertEqual(
            compiled["combined_packet_sha256"],
            hashlib.sha256(compiled["packet_text"].encode("utf-8")).hexdigest(),
        )

        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "migrated.md"
            metadata = Path(td) / "migration.json"
            with redirect_stdout(io.StringIO()):
                exit_code = compiler.main(
                    [
                        "--root",
                        str(ROOT),
                        "migrate-packet",
                        "--legacy",
                        str(FIXTURES / "member-goal-packet-legacy.json"),
                        "--output",
                        str(output),
                        "--metadata",
                        str(metadata),
                    ]
                )
            self.assertEqual(exit_code, 0)
            sidecar = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["legacy_digest_status"], "legacy/unavailable")
            self.assertIsNone(sidecar["legacy_combined_packet_sha256"])
            self.assertEqual(
                sidecar["compiled"]["combined_packet_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )

    def test_install_allowlist_covers_compiler_sources_and_fixtures(self) -> None:
        manifest = (ROOT / "scripts" / "install" / "package-manifest.txt").read_text(
            encoding="utf-8"
        )
        for entry in (
            "prefix scripts/",
            "prefix subagents/",
            "prefix prompts/",
            "prefix references/",
            "prefix tests/v23/",
        ):
            self.assertIn(entry, manifest)


if __name__ == "__main__":
    unittest.main()
