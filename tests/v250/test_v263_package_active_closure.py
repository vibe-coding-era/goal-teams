from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEVELOPS = ROOT / "develops"
CHECKER = ROOT / "scripts/checks/check-package-manifest.py"
PACKAGE_MANIFEST = ROOT / "scripts/install/package-manifest.txt"
ACTIVE_PATH = "references/current/ACTIVE.json"
V266_ACTIVATION_PATH = (
    "references/current/generations/V2.66/activation-manifest.json"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_package_manifest_v266_active_closure", CHECKER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load package checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package_selection(checker) -> set[str]:
    rules: list[tuple[str, str]] = []
    for raw in PACKAGE_MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            kind, value = line.split(maxsplit=1)
            rules.append((kind, value))
    selected, errors = checker._selected_paths(ROOT, rules)
    if errors:
        raise AssertionError(errors)
    return selected


def _canonical_digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TestV266PackageActiveClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = _load_checker()
        cls.selected = _package_selection(cls.checker)
        DEVELOPS.mkdir(exist_ok=True)

    def _v266_cutover_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(
            prefix="v266-package-active-closure-", dir=DEVELOPS
        )
        root = Path(temporary.name)
        activation = copy.deepcopy(
            json.loads((ROOT / V266_ACTIVATION_PATH).read_text(encoding="utf-8"))
        )
        activation["generation_state"] = "active"
        for entries in activation["root_sets"].values():
            for entry in entries:
                relative = entry["path"]
                source = ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                raw = destination.read_bytes()
                entry["sha256"] = hashlib.sha256(raw).hexdigest()
                entry["bytes"] = len(raw)
        supplement = sorted(
            self.selected - set(activation["current_default_allowlist"])
        )
        activation["package_supplement_allowlist"] = supplement
        activation["package_supplement_allowlist_digest"] = _canonical_digest(
            supplement
        )
        activation["manifest_payload_sha256"] = "0" * 64
        activation["manifest_payload_sha256"] = _canonical_digest(
            {
                key: value
                for key, value in activation.items()
                if key != "manifest_payload_sha256"
            }
        )
        activation_file = root / V266_ACTIVATION_PATH
        activation_file.parent.mkdir(parents=True, exist_ok=True)
        activation_raw = (
            json.dumps(activation, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        activation_file.write_bytes(activation_raw)
        active_file = root / ACTIVE_PATH
        active_file.parent.mkdir(parents=True, exist_ok=True)
        active_file.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-active-generation-v1",
                    "generation_id": "V2.66",
                    "activation_manifest": V266_ACTIVATION_PATH,
                    "activation_manifest_sha256": hashlib.sha256(
                        activation_raw
                    ).hexdigest(),
                    "state": "active_current",
                    "updated_at": "2026-08-12T00:00:00+08:00",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return temporary, root

    def test_package_selection_fails_closed_for_pre_cutover_v265_active(self) -> None:
        temporary = tempfile.TemporaryDirectory(
            prefix="v265-package-active-closure-", dir=DEVELOPS
        )
        try:
            root = Path(temporary.name)
            active_file = root / ACTIVE_PATH
            active_file.parent.mkdir(parents=True, exist_ok=True)
            activation_path = (
                "references/current/generations/V2.65/activation-manifest.json"
            )
            active_file.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-active-generation-v1",
                        "generation_id": "V2.65",
                        "activation_manifest": activation_path,
                        "activation_manifest_sha256": "0" * 64,
                        "state": "active_current",
                        "updated_at": "2026-08-12T00:00:00+08:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            errors = self.checker._active_package_closure(root, self.selected)
            self.assertIn(
                "E_CURRENT_PACKAGE_ACTIVE_ACTIVATION_NOT_SELECTED:"
                + activation_path,
                errors,
            )
        finally:
            temporary.cleanup()

    def test_same_package_selection_passes_after_v266_active_cutover(self) -> None:
        temporary, root = self._v266_cutover_fixture()
        try:
            self.assertEqual(
                [], self.checker._active_package_closure(root, self.selected)
            )
        finally:
            temporary.cleanup()

    def test_active_activation_and_generation_digests_are_exact(self) -> None:
        temporary, root = self._v266_cutover_fixture()
        try:
            active_path = root / ACTIVE_PATH
            active = json.loads(active_path.read_text(encoding="utf-8"))
            active["activation_manifest_sha256"] = "0" * 64
            active_path.write_text(
                json.dumps(active, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "E_CURRENT_PACKAGE_ACTIVE_ACTIVATION_DIGEST_MISMATCH:"
                + V266_ACTIVATION_PATH,
                self.checker._active_package_closure(root, self.selected),
            )

            temporary.cleanup()
            temporary, root = self._v266_cutover_fixture()
            activation = json.loads(
                (root / V266_ACTIVATION_PATH).read_text(encoding="utf-8")
            )
            member = activation["root_sets"]["bootstrap"][0]
            (root / member["path"]).write_bytes(b"tampered\n")
            self.assertIn(
                "E_CURRENT_PACKAGE_ACTIVE_MEMBER_DIGEST_MISMATCH:"
                + member["path"],
                self.checker._active_package_closure(root, self.selected),
            )
        finally:
            temporary.cleanup()

    def test_repository_validation_uses_active_not_version_candidate(self) -> None:
        active = json.loads((ROOT / ACTIVE_PATH).read_text(encoding="utf-8"))
        result = self.checker.validate_manifest(PACKAGE_MANIFEST, replay=False)
        if active["generation_id"] == "V2.65":
            self.assertFalse(result["passed"], result)
            self.assertIn(
                "E_CURRENT_PACKAGE_ACTIVE_ACTIVATION_NOT_SELECTED:"
                + active["activation_manifest"],
                result["errors"],
            )
        else:
            self.assertEqual("V2.66", active["generation_id"])
            self.assertTrue(result["passed"], result)


if __name__ == "__main__":
    unittest.main()
