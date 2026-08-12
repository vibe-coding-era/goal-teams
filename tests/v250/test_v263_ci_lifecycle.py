from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github/workflows/check.yml",
    ROOT / ".github/workflows/release-gate.yml",
)
SHARED_ACTIVE_PRE_RELEASE_MODULES = (
    "tests.v250.test_package_isolation",
    "tests.v250.test_release_checker",
    "tests.v250.test_release_control",
    "tests.v250.test_release_flow",
    "tests.v250.test_release_runtime_support",
    "tests.v250.test_runtime_cli",
    "tests.v250.test_runtime_host_adapter",
    "tests.v250.test_runtime_transition",
    "tests.v250.test_s4_executor",
    "tests.v250.test_schema_contracts",
    "tests.v250.test_v252_loop_bootstrap",
    "tests.v250.test_v252_loop_bootstrap_hardening",
    "tests.v250.test_v252_loop_bootstrap_receipt_hardening",
    "tests.v250.test_workflow_release_contract",
)


def actual_v263_test_modules() -> tuple[str, ...]:
    paths = sorted((ROOT / "tests/v250").glob("test_v263*.py"))
    paths.extend(sorted((ROOT / "tests/v263").glob("test_*.py")))
    return tuple(
        path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        for path in paths
    )


ACTIVE_PRE_RELEASE_MODULES = (
    *SHARED_ACTIVE_PRE_RELEASE_MODULES,
    *actual_v263_test_modules(),
)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def development_step(workflow: str) -> str:
    marker = "      - name: Active V2.63 pre-release exact Development gate"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    if end < 0:
        end = workflow.find("\n  ", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


class TestV263CiLifecycle(unittest.TestCase):
    def test_development_jobs_use_one_explicit_active_pre_release_exact_set(
        self,
    ) -> None:
        observed: list[list[str]] = []
        for path in WORKFLOWS:
            with self.subTest(path=path.name):
                workflow = text(path)
                self.assertNotIn("unittest discover", workflow)
                step = development_step(workflow)
                self.assertIn("python3 -m unittest -v \\", step)
                module_tokens = [
                    line.strip().removesuffix("\\").strip()
                    for line in step.splitlines()
                    if line.strip().startswith("tests.")
                ]
                self.assertEqual(len(module_tokens), len(set(module_tokens)))
                self.assertEqual(set(ACTIVE_PRE_RELEASE_MODULES), set(module_tokens))
                observed.append(module_tokens)
        self.assertEqual(observed[0], observed[1])

    def test_exact_set_constant_covers_shared_and_actual_v263_tests_once(self) -> None:
        self.assertEqual(
            len(ACTIVE_PRE_RELEASE_MODULES),
            len(set(ACTIVE_PRE_RELEASE_MODULES)),
        )
        self.assertEqual(
            set(ACTIVE_PRE_RELEASE_MODULES),
            set(SHARED_ACTIVE_PRE_RELEASE_MODULES) | set(actual_v263_test_modules()),
        )

    def test_active_pre_release_phase_commands_are_explicit_and_ordered(self) -> None:
        commands = (
            "scripts/checks/check-version-sync.py \\",
            "--mode development \\",
            "--published-version V2.62",
            "scripts/checks/validate-v250-generation.py \\",
            "--generation-id V2.63 \\",
            "--selection active",
            "scripts/checks/check-v250.py \\",
            "--phase development \\",
            "--project-size medium \\",
            "--stage candidate",
            "scripts/checks/check-package-manifest.py",
        )
        for path in WORKFLOWS:
            with self.subTest(path=path.name):
                step = development_step(text(path))
                positions = [step.index(command) for command in commands]
                self.assertEqual(sorted(positions), positions)
                self.assertNotIn("--phase release", step)

    def test_formal_release_workflow_keeps_facts_s1_and_single_s2(self) -> None:
        workflow = text(ROOT / ".github/workflows/release-gate.yml")
        self.assertIn("derived_route = derive_route(project_route_facts)", workflow)
        self.assertIn(
            "receipt = compile_derived_route_closure(root, generation, derived_route)",
            workflow,
        )
        self.assertIn("--phase release", workflow)
        self.assertIn("Run exact Current full regression", workflow)
        self.assertEqual(1, workflow.count("scripts/release/build-release.py"))


if __name__ == "__main__":
    unittest.main()
