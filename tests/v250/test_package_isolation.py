from __future__ import annotations

import importlib.util
import os
import py_compile
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts/checks/check-package-manifest.py"
HAS_REPLAY_SUPPLEMENT = (REPO / "references/legacy-replay/manifest.json").is_file()
INSTALLER = REPO / "scripts/install/install-local.sh"
DEVELOPS = REPO / "develops"


def _load_checker():
    spec = importlib.util.spec_from_file_location("v250_package_checker", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load package checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _embedded_installer_namespace(work: Path) -> dict[str, object]:
    shell = INSTALLER.read_text(encoding="utf-8")
    embedded = shell.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]
    embedded = embedded.split("\nfor handled_signal in ", 1)[0]
    argv = [
        "install-local-embedded.py",
        str(REPO),
        "--release-bundle",
        str(work / "bundle"),
        "--release-identity",
        str(work / "identity.json"),
    ]
    namespace: dict[str, object] = {"__name__": "goal_teams_v250_installer_test"}
    environment = {
        "HOME": str(work),
        "CODEX_HOME": str(work / ".codex"),
        "PATH": os.environ.get("PATH", ""),
    }
    with mock.patch.dict(os.environ, environment, clear=False), mock.patch.object(
        sys, "argv", argv
    ):
        exec(compile(embedded, str(INSTALLER), "exec"), namespace)
    return namespace


def _workspace_tempdir(prefix: str) -> tempfile.TemporaryDirectory[str]:
    DEVELOPS.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=DEVELOPS)


class TestV250PackageIsolation(unittest.TestCase):
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

    def test_installer_can_load_v250_prompt_identity_modules(self) -> None:
        with _workspace_tempdir("goal-teams-v250-installer-") as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            loader = runtime["load_python_module"]
            module_name = "_goal_teams_v250_generation_probe"
            try:
                module = loader(
                    module_name,
                    REPO,
                    "scripts/v250/generation_runtime.py",
                    ("load_generation",),
                )
                self.assertTrue(callable(module.load_generation))
                self.assertEqual(
                    REPO / "scripts/v250/generation_runtime.py",
                    Path(module.__file__),
                )
            finally:
                sys.modules.pop(module_name, None)

    def test_installer_loader_rejects_escape_and_symlink_ancestor(self) -> None:
        with _workspace_tempdir("goal-teams-v250-loader-boundary-") as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            loader = runtime["load_python_module"]
            install_error = runtime["InstallError"]
            root = work / "root"
            outside = work / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "probe.py").write_text(
                "def marker():\n    return 'outside'\n", encoding="utf-8"
            )
            (root / "linked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(install_error):
                loader(
                    "_goal_teams_v250_escape_probe",
                    root,
                    "../outside/probe.py",
                    ("marker",),
                )
            with self.assertRaises(install_error):
                loader(
                    "_goal_teams_v250_symlink_probe",
                    root,
                    "linked/probe.py",
                    ("marker",),
                )
            self.assertNotIn("_goal_teams_v250_escape_probe", sys.modules)
            self.assertNotIn("_goal_teams_v250_symlink_probe", sys.modules)

    def test_installer_loader_uses_source_bytes_not_forged_pyc(self) -> None:
        with _workspace_tempdir("goal-teams-v250-loader-pyc-") as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            loader = runtime["load_python_module"]
            root = work / "root"
            root.mkdir()
            source = root / "probe.py"
            source.write_text(
                "def marker():\n    return 'from-pyc'\n", encoding="utf-8"
            )
            original = source.stat()
            pyc_path = Path(py_compile.compile(str(source), doraise=True))
            self.assertTrue(pyc_path.is_file())
            source.write_text(
                "def marker():\n    return 'from-src'\n", encoding="utf-8"
            )
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
            module_name = "_goal_teams_v250_pyc_probe"
            try:
                module = loader(module_name, root, "probe.py", ("marker",))
                self.assertEqual("from-src", module.marker())
            finally:
                sys.modules.pop(module_name, None)

    def test_installer_loader_fails_closed_on_system_exit_and_missing_symbol(self) -> None:
        with _workspace_tempdir("goal-teams-v250-loader-fail-closed-") as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            loader = runtime["load_python_module"]
            install_error = runtime["InstallError"]
            root = work / "root"
            root.mkdir()
            (root / "exit.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            (root / "missing.py").write_text("VALUE = 1\n", encoding="utf-8")

            with self.assertRaises(install_error):
                loader("_goal_teams_v250_exit_probe", root, "exit.py", ())
            with self.assertRaises(install_error):
                loader(
                    "_goal_teams_v250_missing_probe",
                    root,
                    "missing.py",
                    ("required_callable",),
                )
            self.assertNotIn("_goal_teams_v250_exit_probe", sys.modules)
            self.assertNotIn("_goal_teams_v250_missing_probe", sys.modules)

    def test_installer_prompt_identity_fails_closed_on_deferred_system_exit(self) -> None:
        with _workspace_tempdir("goal-teams-v250-deferred-exit-") as directory:
            runtime = _embedded_installer_namespace(Path(directory))
            install_error = runtime["InstallError"]

            def deferred_exit(*_args: object, **_kwargs: object) -> object:
                raise SystemExit(0)

            scenarios = (
                (
                    "generation",
                    types.SimpleNamespace(load_generation=deferred_exit),
                    types.SimpleNamespace(
                        compile_route_closure=lambda *_args, **_kwargs: {}
                    ),
                ),
                (
                    "closure",
                    types.SimpleNamespace(load_generation=lambda _root: {}),
                    types.SimpleNamespace(compile_route_closure=deferred_exit),
                ),
            )
            for label, generation_module, closure_module in scenarios:
                with self.subTest(label=label):
                    runtime["load_v250_prompt_modules"] = lambda _root: (
                        generation_module,
                        closure_module,
                    )
                    with self.assertRaises(install_error):
                        runtime["compute_prompt_identity"](REPO)

    def test_installer_restores_prepolluted_canonical_modules(self) -> None:
        with _workspace_tempdir("goal-teams-v250-loader-isolation-") as directory:
            runtime = _embedded_installer_namespace(Path(directory))
            loader = runtime["load_v250_prompt_modules"]
            names = (
                "scripts",
                "scripts.v250",
                "scripts.v250.generation_runtime",
                "scripts.v250.route_closure",
            )
            missing = object()
            originals = {name: sys.modules.get(name, missing) for name in names}
            poisons = {name: types.ModuleType(name) for name in names}
            try:
                sys.modules.update(poisons)
                generation, closure = loader(REPO)
                self.assertEqual(
                    REPO / "scripts/v250/generation_runtime.py",
                    Path(generation.__file__),
                )
                self.assertEqual(
                    REPO / "scripts/v250/route_closure.py",
                    Path(closure.__file__),
                )
                for symbol in (
                    "canonical_json_digest",
                    "resolve_repo_file",
                    "sha256_bytes",
                ):
                    self.assertIs(getattr(generation, symbol), getattr(closure, symbol))
                for name in names:
                    self.assertIs(poisons[name], sys.modules[name])
            finally:
                for name, original in originals.items():
                    if original is missing:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = original

    def test_installer_computes_v250_startup_prompt_identity(self) -> None:
        with _workspace_tempdir("goal-teams-v250-installer-") as directory:
            runtime = _embedded_installer_namespace(Path(directory))
            identity = runtime["compute_prompt_identity"](REPO)
        self.assertTrue(identity["passed"])
        self.assertEqual("goal-teams-prompt-identity-v2.50", identity["prompt_identity_version"])
        self.assertEqual("V250-ROUTE-STARTUP", identity["route_id"])

    def test_installer_runs_current_source_validation_with_prompt_identity(self) -> None:
        with _workspace_tempdir("goal-teams-v250-installer-") as directory:
            runtime = _embedded_installer_namespace(Path(directory))
            identity = runtime["compute_prompt_identity"](REPO)
            runtime["source_info"].update(
                {
                    "runtime_prompt_refs": identity["ordered_refs"],
                    "prefix_manifest_sha256": identity["prefix_manifest_sha256"],
                    "route_static_digest": identity["route_static_digest"],
                }
            )
            runtime["validate_skill"](REPO, "v250_source_test")
            results = runtime["validation_results"]
        self.assertTrue(results)
        self.assertTrue(all(result["status"] == "passed" for result in results))
        self.assertIn(
            "scripts/checks/check-v266.py --phase development",
            {result["command"] for result in results},
        )
        self.assertIn(
            "scripts/v250/generation_runtime.py:V250-ROUTE-STARTUP",
            {result["command"] for result in results},
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
