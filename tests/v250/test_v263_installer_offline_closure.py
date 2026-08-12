from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.v250.test_package_isolation import _embedded_installer_namespace


class TestV263InstallerOfflineClosure(unittest.TestCase):
    def _root(self, work: Path, generation_id: str) -> Path:
        root = work / generation_id
        (root / "references/current").mkdir(parents=True)
        (root / "scripts/v250").mkdir(parents=True)
        (root / "references/current/ACTIVE.json").write_text(
            json.dumps({"generation_id": generation_id}),
            encoding="utf-8",
        )
        for relative in (
            "scripts/v250/generation_runtime.py",
            "scripts/v250/route_closure.py",
        ):
            (root / relative).write_text("# fixture\n", encoding="utf-8")
        return root

    def test_v263_uses_declared_offline_closure_without_direct_route_compilation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            root = self._root(work, "V2.63")
            generation = {
                "generation_id": "V2.63",
                "activation_digest_verified": True,
                "activation_manifest_sha256": "a" * 64,
                "prompt_manifest_sha256": "b" * 64,
            }
            closure = {
                "loaded_paths": [
                    "references/current/generations/V2.63/core.md",
                ],
                "legacy_intersection": [],
            }
            calls: list[tuple[Path, object, str]] = []

            def declared(
                observed_root: Path,
                observed_generation: object,
                *,
                route_id: str,
            ) -> dict[str, object]:
                calls.append((observed_root, observed_generation, route_id))
                return closure

            def direct(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("V2.63 installer used direct route compilation")

            runtime["load_v250_prompt_modules"] = lambda _root: (
                SimpleNamespace(load_generation=lambda _root: generation),
                SimpleNamespace(
                    compile_route_closure=direct,
                    validate_declared_route_closure=declared,
                ),
            )

            identity = runtime["compute_prompt_identity"](root)

            self.assertEqual(
                [(root, generation, "V250-ROUTE-STARTUP")],
                calls,
            )
            self.assertEqual(closure["loaded_paths"], identity["ordered_refs"])
            self.assertEqual("verified", identity["manifest_status"])

    def test_predecessor_generation_keeps_legacy_direct_route_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            runtime = _embedded_installer_namespace(work)
            root = self._root(work, "V2.62")
            generation = {
                "generation_id": "V2.62",
                "activation_digest_verified": True,
                "activation_manifest_sha256": "a" * 64,
                "prompt_manifest_sha256": "b" * 64,
            }
            closure = {
                "loaded_paths": [
                    "references/current/generations/V2.62/core.md",
                ],
                "legacy_intersection": [],
            }
            calls: list[str] = []

            def direct(
                _root: Path,
                _generation: object,
                *,
                route_id: str,
            ) -> dict[str, object]:
                calls.append(route_id)
                return closure

            def declared(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("predecessor route unexpectedly changed")

            runtime["load_v250_prompt_modules"] = lambda _root: (
                SimpleNamespace(load_generation=lambda _root: generation),
                SimpleNamespace(
                    compile_route_closure=direct,
                    validate_declared_route_closure=declared,
                ),
            )

            runtime["compute_prompt_identity"](root)

            self.assertEqual(["V250-ROUTE-STARTUP"], calls)


if __name__ == "__main__":
    unittest.main()
