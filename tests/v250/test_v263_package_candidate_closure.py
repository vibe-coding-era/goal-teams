from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
DEVELOPS = ROOT / "develops"
CHECKER = ROOT / "scripts/checks/check-package-manifest.py"
PACKAGE_MANIFEST = ROOT / "scripts/install/package-manifest.txt"
ACTIVE_PATH = "references/current/ACTIVE.json"
GENERATION = "V2.66"
ACTIVATION_PATH = (
    "references/current/generations/V2.66/activation-manifest.json"
)
SUPPLEMENT_PATH = "release/current/README.md"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_package_manifest_v266_candidate_closure", CHECKER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load package checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TestV266PackageCandidateClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = _load_checker()
        DEVELOPS.mkdir(exist_ok=True)

    def _fixture(
        self, *, generation_state: str
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, set[str], str]:
        temporary = tempfile.TemporaryDirectory(
            prefix="v266-package-candidate-", dir=DEVELOPS
        )
        root = Path(temporary.name)
        activation = copy.deepcopy(
            json.loads((ROOT / ACTIVATION_PATH).read_text(encoding="utf-8"))
        )
        activation["generation_state"] = generation_state
        for entries in activation["root_sets"].values():
            for entry in entries:
                relative = entry["path"]
                source = ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if relative == "VERSION":
                    destination.write_text("V9.99\n", encoding="utf-8")
                raw = destination.read_bytes()
                entry["sha256"] = hashlib.sha256(raw).hexdigest()
                entry["bytes"] = len(raw)
        self.assertNotIn(SUPPLEMENT_PATH, activation["current_default_allowlist"])
        supplement_destination = root / SUPPLEMENT_PATH
        supplement_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / SUPPLEMENT_PATH, supplement_destination)
        activation["package_supplement_allowlist"] = [SUPPLEMENT_PATH]
        activation["package_supplement_allowlist_digest"] = _canonical_digest(
            [SUPPLEMENT_PATH]
        )
        activation["manifest_payload_sha256"] = "0" * 64
        activation["manifest_payload_sha256"] = _canonical_digest(
            {
                key: value
                for key, value in activation.items()
                if key != "manifest_payload_sha256"
            }
        )
        activation_file = root / ACTIVATION_PATH
        activation_file.parent.mkdir(parents=True, exist_ok=True)
        activation_raw = (
            json.dumps(activation, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        activation_file.write_bytes(activation_raw)

        active_file = root / ACTIVE_PATH
        active_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / ACTIVE_PATH, active_file)
        # The activation above binds an intentionally unrelated VERSION value;
        # identity still comes only from the explicit candidate CLI pair.
        manifest = root / "scripts/install/package-manifest.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACKAGE_MANIFEST, manifest)
        selected = set(activation["current_default_allowlist"]) | {SUPPLEMENT_PATH}
        return (
            temporary,
            root,
            selected,
            hashlib.sha256(activation_raw).hexdigest(),
        )

    def test_candidate_closure_uses_explicit_identity_across_active_phases(
        self,
    ) -> None:
        temporary, root, selected, digest = self._fixture(
            generation_state="inactive_candidate"
        )
        try:
            active_raw = (root / ACTIVE_PATH).read_bytes()
            active = json.loads((root / ACTIVE_PATH).read_text(encoding="utf-8"))
            self.assertIn(active["generation_id"], {"V2.65", "V2.66"})
            self.assertEqual(
                [],
                self.checker._candidate_package_closure(
                    root,
                    selected,
                    generation_id=GENERATION,
                    expected_activation_sha256=digest,
                ),
            )
            self.assertEqual(active_raw, (root / ACTIVE_PATH).read_bytes())
        finally:
            temporary.cleanup()

    def test_candidate_closure_accepts_prospective_active_manifest_state(
        self,
    ) -> None:
        temporary, root, selected, digest = self._fixture(
            generation_state="active"
        )
        try:
            self.assertEqual(
                [],
                self.checker._candidate_package_closure(
                    root,
                    selected,
                    generation_id=GENERATION,
                    expected_activation_sha256=digest,
                ),
            )
        finally:
            temporary.cleanup()

    def test_candidate_closure_binds_activation_member_and_allowlist(self) -> None:
        temporary, root, selected, digest = self._fixture(
            generation_state="inactive_candidate"
        )
        try:
            wrong_digest_errors = self.checker._candidate_package_closure(
                root,
                selected,
                generation_id=GENERATION,
                expected_activation_sha256="0" * 64,
            )
            self.assertIn(
                "E_CANDIDATE_PACKAGE_ACTIVATION_DIGEST_MISMATCH:"
                + ACTIVATION_PATH,
                wrong_digest_errors,
            )

            activation = json.loads(
                (root / ACTIVATION_PATH).read_text(encoding="utf-8")
            )
            member = activation["root_sets"]["bootstrap"][0]["path"]
            (root / member).write_bytes(b"tampered\n")
            member_errors = self.checker._candidate_package_closure(
                root,
                selected,
                generation_id=GENERATION,
                expected_activation_sha256=digest,
            )
            self.assertIn(
                "E_CANDIDATE_PACKAGE_MEMBER_DIGEST_MISMATCH:" + member,
                member_errors,
            )

            selected.remove(member)
            selected_errors = self.checker._candidate_package_closure(
                root,
                selected,
                generation_id=GENERATION,
                expected_activation_sha256=digest,
            )
            self.assertIn(
                "E_CANDIDATE_PACKAGE_MEMBER_NOT_SELECTED:" + member,
                selected_errors,
            )
        finally:
            temporary.cleanup()

    def test_candidate_closure_requires_exact_selected_and_supplement_sets(self) -> None:
        temporary, root, selected, digest = self._fixture(
            generation_state="inactive_candidate"
        )
        try:
            missing = set(selected)
            missing.remove(SUPPLEMENT_PATH)
            self.assertIn(
                "E_CANDIDATE_PACKAGE_SUPPLEMENT_NOT_SELECTED:" + SUPPLEMENT_PATH,
                self.checker._candidate_package_closure(
                    root,
                    missing,
                    generation_id=GENERATION,
                    expected_activation_sha256=digest,
                ),
            )

            extra = set(selected) | {"undeclared-package-extra.txt"}
            self.assertIn(
                "E_CANDIDATE_PACKAGE_SELECTED_UNDECLARED:undeclared-package-extra.txt",
                self.checker._candidate_package_closure(
                    root,
                    extra,
                    generation_id=GENERATION,
                    expected_activation_sha256=digest,
                ),
            )

            activation_file = root / ACTIVATION_PATH
            activation = json.loads(activation_file.read_text(encoding="utf-8"))
            activation["package_supplement_allowlist_digest"] = "0" * 64
            activation["manifest_payload_sha256"] = _canonical_digest(
                {
                    key: value
                    for key, value in activation.items()
                    if key != "manifest_payload_sha256"
                }
            )
            raw = (
                json.dumps(activation, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            activation_file.write_bytes(raw)
            self.assertIn(
                "E_CANDIDATE_PACKAGE_SUPPLEMENT_DIGEST_MISMATCH",
                self.checker._candidate_package_closure(
                    root,
                    selected,
                    generation_id=GENERATION,
                    expected_activation_sha256=hashlib.sha256(raw).hexdigest(),
                ),
            )
        finally:
            temporary.cleanup()

    def test_cli_candidate_mode_dispatches_paired_explicit_identity(self) -> None:
        temporary, root, selected, digest = self._fixture(
            generation_state="inactive_candidate"
        )
        try:
            manifest = root / "scripts/install/package-manifest.txt"
            argv = [
                "check-package-manifest.py",
                "--manifest",
                str(manifest),
                "--candidate-generation",
                GENERATION,
                "--activation-sha256",
                digest,
            ]
            output = io.StringIO()
            with (
                mock.patch.object(self.checker, "ROOT", root),
                mock.patch.object(
                    self.checker,
                    "_selected_paths",
                    return_value=(selected, []),
                ),
                mock.patch.object(sys, "argv", argv),
                redirect_stdout(output),
            ):
                self.assertEqual(0, self.checker.main())
            result = json.loads(output.getvalue())
            self.assertTrue(result["passed"], result)
            self.assertEqual("candidate", result["mode"])
            self.assertEqual(GENERATION, result["candidate_generation"])
            self.assertEqual(digest, result["activation_sha256"])
        finally:
            temporary.cleanup()

    def test_cli_rejects_unpaired_or_replay_candidate_identity(self) -> None:
        argv = ["check-package-manifest.py", "--candidate-generation", GENERATION]
        with self.assertRaises(SystemExit):
            with mock.patch.object(sys, "argv", argv):
                self.checker.parse_args()
        argv = [
            "check-package-manifest.py",
            "--replay",
            "--candidate-generation",
            GENERATION,
            "--activation-sha256",
            "0" * 64,
        ]
        with self.assertRaises(SystemExit):
            with mock.patch.object(sys, "argv", argv):
                self.checker.parse_args()


if __name__ == "__main__":
    unittest.main()
