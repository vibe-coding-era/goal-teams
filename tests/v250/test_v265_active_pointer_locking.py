from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.v250 import generation_runtime
from scripts.v250 import refresh_generation_manifests as refresh
from tests.v250.v265_activation_fixture import V265ActivationFixture


REPO = pathlib.Path(__file__).resolve().parents[2]
ACTIVE = pathlib.Path("references/current/ACTIVE.json")
V265_ACTIVATION = pathlib.Path(
    "references/current/generations/V2.65/activation-manifest.json"
)
REFRESH = pathlib.Path("scripts/v250/refresh_generation_manifests.py")
ACTIVATED_AT = "2026-08-22T18:30:00+08:00"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class TestV265ActivePointerLocking(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name) / "repo"
        self.runtime_tmp = pathlib.Path(self.temporary.name) / "runtime-tmp"
        self.runtime_tmp.mkdir(mode=0o700)
        self.environment = dict(os.environ)
        self.environment["TMPDIR"] = str(self.runtime_tmp)
        self.fixture = V265ActivationFixture.copy_from(
            REPO,
            self.root,
            environment=self.environment,
        )
        self.base_active_sha256 = self.fixture.base_active_sha256
        self.base_activation_sha256 = self.fixture.base_activation_sha256

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_refresh(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.fixture.run_refresh(*arguments)

    def prepare_active(self) -> str:
        result = self.fixture.prepare_v265()
        self.assertEqual(0, result.returncode, result.stdout)
        self.base_active_sha256 = self.fixture.base_active_sha256
        self.base_activation_sha256 = self.fixture.base_activation_sha256
        return sha256((self.root / V265_ACTIVATION).read_bytes())

    def activate_arguments(self, prepared_digest: str) -> tuple[str, ...]:
        return (
            "--activate",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            self.base_active_sha256,
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_digest,
            "--activated-at",
            ACTIVATED_AT,
        )

    def lock_path(self) -> pathlib.Path:
        exact_active = (self.root / ACTIVE).resolve(strict=True)
        name = hashlib.sha256(os.fsencode(str(exact_active))).hexdigest() + ".lock"
        return (
            pathlib.Path("/tmp").resolve(strict=True)
            / f"goal-teams-active-locks-{os.getuid()}"
            / name
        )

    def hold_lock(self) -> tuple[int, pathlib.Path]:
        lock_path = self.lock_path()
        lock_path.parent.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor, lock_path

    def test_all_writer_modes_share_exact_active_lock_and_timeout(self) -> None:
        descriptor, _lock_path = self.hold_lock()
        active_before = (self.root / ACTIVE).read_bytes()
        try:
            candidate = self.run_refresh(
                "--write",
                "--generation-id",
                "V2.65",
                "--predecessor",
                "V2.63",
                "--base-activation-sha256",
                self.base_activation_sha256,
                "--lock-timeout-seconds",
                "0",
            )
            prepared = self.run_refresh(
                "--prepare-active",
                "--generation-id",
                "V2.65",
                "--predecessor",
                "V2.63",
                "--base-active-sha256",
                self.base_active_sha256,
                "--base-activation-sha256",
                self.base_activation_sha256,
                "--lock-timeout-seconds",
                "0",
            )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        for result in (candidate, prepared):
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("ACTIVE lock timeout", result.stdout)
        self.assertEqual(active_before, (self.root / ACTIVE).read_bytes())

        prepared_digest = self.prepare_active()
        descriptor, _lock_path = self.hold_lock()
        try:
            activated = self.run_refresh(
                *self.activate_arguments(prepared_digest),
                "--lock-timeout-seconds",
                "0",
            )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        self.assertNotEqual(0, activated.returncode, activated.stdout)
        self.assertIn("ACTIVE lock timeout", activated.stdout)
        self.assertEqual(active_before, (self.root / ACTIVE).read_bytes())

    def test_lock_file_symlink_attack_fails_closed(self) -> None:
        lock_path = self.lock_path()
        lock_path.parent.mkdir(mode=0o700, exist_ok=True)
        victim = pathlib.Path(self.temporary.name) / "victim"
        victim.write_text("unchanged\n", encoding="utf-8")
        lock_path.symlink_to(victim)
        active_before = (self.root / ACTIVE).read_bytes()

        result = self.run_refresh(
            "--write",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--lock-timeout-seconds",
            "0",
        )

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn("ACTIVE lock file is unsafe", result.stdout)
        self.assertEqual("unchanged\n", victim.read_text(encoding="utf-8"))
        self.assertEqual(active_before, (self.root / ACTIVE).read_bytes())

    def test_two_concurrent_activators_serialize_and_only_one_wins(self) -> None:
        prepared_digest = self.prepare_active()
        read_fd, write_fd = os.pipe()
        wrapper = (
            "import os,sys; "
            "fd=int(sys.argv[1]); os.read(fd,1); os.close(fd); "
            "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])"
        )
        processes = []
        for index in range(2):
            environment = dict(self.environment)
            distinct_tmp = pathlib.Path(self.temporary.name) / f"runtime-{index}"
            distinct_tmp.mkdir(mode=0o700)
            environment["TMPDIR"] = str(distinct_tmp)
            processes.append(subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    wrapper,
                    str(read_fd),
                    str(self.root / REFRESH),
                    *self.activate_arguments(prepared_digest),
                ],
                cwd=self.root,
                env=environment,
                pass_fds=(read_fd,),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ))
        os.close(read_fd)
        os.write(write_fd, b"xx")
        os.close(write_fd)
        results = []
        for process in processes:
            output, _unused = process.communicate(timeout=20)
            results.append((process.returncode, output))

        self.assertEqual(1, sum(code == 0 for code, _out in results), results)
        self.assertTrue(
            any("raw ACTIVE CAS mismatch" in output for _code, output in results),
            results,
        )
        active = json.loads((self.root / ACTIVE).read_bytes())
        self.assertEqual("V2.65", active["generation_id"])
        self.assertEqual(prepared_digest, active["activation_manifest_sha256"])

    def test_inserted_pointer_update_between_validation_windows_is_preserved(self) -> None:
        prepared_digest = self.prepare_active()
        concurrent = json.loads((self.root / ACTIVE).read_bytes())
        concurrent["updated_at"] = "2026-08-22T18:29:00+08:00"
        concurrent_raw = refresh._json_bytes(concurrent)
        arguments = [
            str(self.root / REFRESH),
            *self.activate_arguments(prepared_digest),
        ]
        original_loader = generation_runtime.load_prepared_generation
        calls = 0

        def load_then_insert(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original_loader(*args, **kwargs)
            if calls == 1:
                refresh._atomic_write(ACTIVE, concurrent_raw)
            return result

        with mock.patch.object(refresh, "ROOT", self.root), mock.patch.object(
            generation_runtime,
            "load_prepared_generation",
            side_effect=load_then_insert,
        ), mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(ValueError, "raw ACTIVE CAS mismatch"):
                refresh.main()

        self.assertEqual(1, calls)
        self.assertEqual(concurrent_raw, (self.root / ACTIVE).read_bytes())

    def test_failed_readback_preserves_inserted_concurrent_pointer(self) -> None:
        prepared_digest = self.prepare_active()
        base = json.loads((self.root / ACTIVE).read_bytes())
        concurrent = dict(base)
        concurrent["updated_at"] = "2026-08-22T18:31:00+08:00"
        concurrent_raw = refresh._json_bytes(concurrent)
        arguments = [
            str(self.root / REFRESH),
            *self.activate_arguments(prepared_digest),
        ]

        def insert_concurrent_pointer(_root: pathlib.Path) -> dict[str, object]:
            refresh._atomic_write(ACTIVE, concurrent_raw)
            raise ValueError("injected post-write readback failure")

        with mock.patch.object(refresh, "ROOT", self.root), mock.patch.object(
            generation_runtime,
            "load_generation",
            side_effect=insert_concurrent_pointer,
        ), mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(RuntimeError, "rollback conflict"):
                refresh.main()

        self.assertEqual(concurrent_raw, (self.root / ACTIVE).read_bytes())

    def test_success_readback_occurs_while_cross_process_lock_is_held(self) -> None:
        prepared_digest = self.prepare_active()
        arguments = [
            str(self.root / REFRESH),
            *self.activate_arguments(prepared_digest),
        ]
        real_load = generation_runtime.load_generation

        def assert_locked(root: pathlib.Path) -> dict[str, object]:
            lock_path = refresh._active_lock_path()
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import fcntl,os,sys; "
                        "fd=os.open(sys.argv[1],os.O_RDWR); "
                        "\ntry: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)"
                        "\nexcept BlockingIOError: raise SystemExit(23)"
                        "\nraise SystemExit(0)"
                    ),
                    str(lock_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(23, probe.returncode, probe.stdout)
            return real_load(root)

        with mock.patch.object(refresh, "ROOT", self.root), mock.patch.object(
            generation_runtime,
            "load_generation",
            side_effect=assert_locked,
        ), mock.patch.object(sys, "argv", arguments):
            self.assertEqual(0, refresh.main())

        active = json.loads((self.root / ACTIVE).read_bytes())
        self.assertEqual("V2.65", active["generation_id"])
        self.assertEqual(prepared_digest, active["activation_manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
