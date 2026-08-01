from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts/checks/check-package-manifest.py"
HAS_REPLAY_SUPPLEMENT = (REPO / "references/legacy-replay/manifest.json").is_file()


def _load_checker():
    spec = importlib.util.spec_from_file_location("v249_package_checker", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load package checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV249PackageIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = _load_checker()

    def test_current_package_selects_no_legacy_or_v23_runtime(self) -> None:
        result = self.checker.validate_manifest(
            REPO / "scripts/install/package-manifest.txt", replay=False
        )

        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual([], result["legacy_intersection"])
        self.assertNotIn(
            "scripts/v23/okf_conformance.py",
            (REPO / "scripts/install/package-manifest.txt").read_text(encoding="utf-8"),
        )

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional Replay supplement is not installed")
    def test_replay_package_has_real_complete_selection(self) -> None:
        manifest_path = REPO / "scripts/install/replay-package-manifest.txt"
        result = self.checker.validate_manifest(manifest_path, replay=True)
        rules = []
        for raw in manifest_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                kind, value = line.split(maxsplit=1)
                rules.append((kind, value))
        selected, selection_errors = self.checker._selected_paths(REPO, rules)
        required, contract_errors = self.checker._replay_required_paths(REPO)

        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual([], selection_errors)
        self.assertEqual([], contract_errors)
        self.assertEqual(required, selected)
        self.assertEqual(len(required), result["selected_path_count"])


if __name__ == "__main__":
    unittest.main()
