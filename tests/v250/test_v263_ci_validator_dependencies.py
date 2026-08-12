from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github/workflows/check.yml",
    ROOT / ".github/workflows/release-gate.yml",
)
MODULE = "tests.v250.test_v263_ci_validator_dependencies"


class TestV263CiValidatorDependencies(unittest.TestCase):
    def test_both_workflows_install_pinned_ajv_outside_the_worktree(self) -> None:
        required_fragments = (
            "VALIDATOR_NODE_PREFIX: ${{ runner.temp }}/goal-teams-v250-node",
            'npm install --prefix "${VALIDATOR_NODE_PREFIX}"',
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "ajv@8.17.1",
            'NODE_PATH="${VALIDATOR_NODE_PREFIX}/node_modules" node -e',
            'echo "NODE_PATH=${VALIDATOR_NODE_PREFIX}/node_modules${NODE_PATH:+:${NODE_PATH}}" >> "${GITHUB_ENV}"',
        )
        combined = "\n".join(
            workflow.read_text(encoding="utf-8") for workflow in WORKFLOWS
        )
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")
                for fragment in required_fragments:
                    self.assertIn(fragment, text)
        for fragment in required_fragments:
            self.assertEqual(3, combined.count(fragment), fragment)

        self.assertEqual(
            1,
            WORKFLOWS[0].read_text(encoding="utf-8").count("ajv@8.17.1"),
        )
        self.assertEqual(
            2,
            WORKFLOWS[1].read_text(encoding="utf-8").count("ajv@8.17.1"),
        )

    def test_dependency_gate_is_in_both_exact_development_sets(self) -> None:
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")
                self.assertEqual(1, text.count(MODULE))


if __name__ == "__main__":
    unittest.main()
