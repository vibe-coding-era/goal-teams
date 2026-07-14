from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
SCANNER_PATH = ROOT / "scripts" / "release" / "public_scan.py"
VERSION = "V2.40"
TAR_NAME = f"goal-teams-{VERSION}.tar.gz"
OKF_PATH = "references/okf-conformance-manifest.json"
PROVIDER_SAMPLE = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
PEM_SAMPLE = (
    b"-----BEGIN " + b"PRIVATE KEY-----\n"
    b"fixture-private-key-material\n"
    b"-----END " + b"PRIVATE KEY-----\n"
)
DETECTOR_SOURCE = b'''import re
HOME_PATH_RE = re.compile("(?:/" + "Users/[^/\\\\s]+|/" + "home/[^/\\\\s]+|[A-Za-z]:\\\\\\\\" + "Users\\\\\\\\[^\\\\\\\\\\\\s]+)", re.I)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.I | re.S)
COMMON_TOKEN_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")
ASSIGNMENT_RE = re.compile(r"(?i)(?:token|password|credential)\\s*[:=]\\s*\\S+")
def contains_secret(text):
    return bool(PRIVATE_KEY_RE.search(text) or COMMON_TOKEN_RE.search(text) or ASSIGNMENT_RE.search(text))
'''


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_public_scan_tests", SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _baseline(assertions: list[dict[str, object]] | None = None) -> bytes:
    return _json_bytes(
        {
            "schema_version": scanner.BASELINE_SCHEMA_VERSION,
            "version": VERSION,
            "review": {
                "reviewer_type": "independent_release_reviewer",
                "independent": True,
                "decision": "accepted",
                "review_id": "v240-independent-review",
            },
            "assertions": assertions or [],
        }
    )


class PublicScanFixture:
    def __init__(self, test: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="v240-public-scan-")
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.snapshot = self.root / "snapshot"
        self.assets_root = self.root / "assets"
        self.source.mkdir()
        self.snapshot.mkdir()
        self.assets_root.mkdir()
        self.assets = {
            name: self.assets_root / name
            for name in (TAR_NAME, "SHA256SUMS", "_release.json", "_files.sha256")
        }

        self._git("init", "-b", "main")
        self._git("config", "user.name", "V240 Scanner Test")
        self._git("config", "user.email", "scanner@example.invalid")
        self._git("config", "commit.gpgSign", "false")
        self.write_source("README.md", b"# Public scanner fixture\n")
        self.write_source("scripts/v23/v236_security.py", DETECTOR_SOURCE)
        self.base_commit = self.commit("base fixture")
        self.write_source("src/app.txt", b"safe candidate content\n")
        self.commit("candidate fixture")

        self.write_snapshot("VERSION", f"{VERSION}\n".encode("utf-8"))
        self.write_snapshot("README.md", b"# Public release fixture\n")
        self.write_snapshot(OKF_PATH, b'{"status":"generated","version":"V2.40"}\n')
        self.rebuild_tar()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.source,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def write_source(self, relative: str, data: bytes) -> None:
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def remove_source(self, relative: str) -> None:
        (self.source / relative).unlink()

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "--no-gpg-sign", "-m", message)
        return self._git("rev-parse", "HEAD")

    def write_snapshot(self, relative: str, data: bytes) -> None:
        path = self.snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _snapshot_entries(
        self, overrides: dict[str, bytes] | None = None
    ) -> list[tuple[str, bytes, str]]:
        values = overrides or {}
        entries: list[tuple[str, bytes, str]] = []
        for path in sorted(item for item in self.snapshot.rglob("*") if item.is_file()):
            relative = path.relative_to(self.snapshot).as_posix()
            entries.append((relative, values.get(relative, path.read_bytes()), "file"))
        return entries

    def _write_tar(
        self,
        entries: Iterable[tuple[str, bytes, str]],
        *,
        uname: str = "root",
        gname: str = "root",
        gzip_filename: str = "",
    ) -> None:
        with self.assets[TAR_NAME].open("wb") as raw:
            with gzip.GzipFile(
                filename=gzip_filename, mode="wb", fileobj=raw, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT
                ) as archive:
                    for relative, data, member_type in entries:
                        info = tarfile.TarInfo(f"goal-teams-{VERSION}/{relative}")
                        info.mode = 0o644
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = uname
                        info.gname = gname
                        if member_type == "file":
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                        elif member_type == "symlink":
                            info.type = tarfile.SYMTYPE
                            info.linkname = data.decode("utf-8")
                            archive.addfile(info)
                        elif member_type == "char-device":
                            info.type = tarfile.CHRTYPE
                            info.devmajor = 1
                            info.devminor = 3
                            archive.addfile(info)
                        else:
                            raise AssertionError(f"unsupported test member: {member_type}")

    def _refresh_manifests(self) -> None:
        tar_digest = _sha256(self.assets[TAR_NAME].read_bytes())
        self.assets["SHA256SUMS"].write_text(
            f"{tar_digest}  {TAR_NAME}\n", encoding="utf-8"
        )
        self.assets["_release.json"].write_bytes(
            _json_bytes({"asset": TAR_NAME, "version": VERSION})
        )
        rows = []
        for path in sorted(item for item in self.snapshot.rglob("*") if item.is_file()):
            relative = path.relative_to(self.snapshot).as_posix()
            rows.append(f"{_sha256(path.read_bytes())}  {relative}")
        self.assets["_files.sha256"].write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

    def rebuild_tar(self, overrides: dict[str, bytes] | None = None) -> None:
        self._write_tar(self._snapshot_entries(overrides))
        self._refresh_manifests()

    def write_custom_tar(
        self, entries: Iterable[tuple[str, bytes, str]]
    ) -> None:
        self._write_tar(entries)
        self._refresh_manifests()

    def scan(self, **overrides: object) -> dict[str, object]:
        candidate = self._git("rev-parse", "HEAD")
        arguments: dict[str, object] = {
            "source_root": self.source,
            "base_commit": self.base_commit,
            "candidate_commit": candidate,
            "candidate_tree": self._git("rev-parse", f"{candidate}^{{tree}}"),
            "version": VERSION,
            "snapshot_root": self.snapshot,
            "asset_paths": self.assets,
            "tag_message": "Goal Teams V2.40",
            "release_title": "Goal Teams V2.40",
            "release_body": "Canonical public release.",
            "checker_digest": _sha256(SCANNER_PATH.read_bytes()),
            "expected_detector_digest": _sha256(DETECTOR_SOURCE),
            "baseline_bytes": _baseline(),
        }
        arguments.update(overrides)
        return scanner.scan_surfaces(**arguments)


class V240PublicScanTests(unittest.TestCase):
    def test_python_checker_and_baseline_bytes_fail_closed(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            scanner._require_python_311((3, 10, 99))
        self.assertEqual(
            str(caught.exception),
            "E_PUBLIC_SCAN_PYTHON: Python 3.11+ required",
        )
        self.assertIsNone(scanner._require_python_311((3, 11, 0)))

        fixture = PublicScanFixture(self)
        with self.assertRaises(scanner.PublicScanError) as checker_error:
            fixture.scan(checker_digest="0" * 64)
        self.assertEqual(
            checker_error.exception.code, "E_PUBLIC_SCAN_CHECKER_DIGEST"
        )

        with self.assertRaises(scanner.PublicScanError) as newline_error:
            scanner.load_baseline(_baseline().rstrip(b"\n"))
        self.assertEqual(
            newline_error.exception.code, "E_PUBLIC_SCAN_BASELINE_CANONICAL"
        )
        duplicate = _baseline().replace(
            b'"version":"V2.40"',
            b'"version":"V2.40","version":"V2.40"',
            1,
        )
        with self.assertRaises(scanner.PublicScanError) as duplicate_error:
            scanner.load_baseline(duplicate)
        self.assertEqual(
            duplicate_error.exception.code, "E_PUBLIC_SCAN_BASELINE_JSON"
        )

    def test_receipt_is_deterministic_portable_and_binds_all_checker_inputs(self) -> None:
        fixture = PublicScanFixture(self)

        first = fixture.scan()
        second = fixture.scan()

        self.assertTrue(first["passed"])
        self.assertEqual(first, second)
        self.assertEqual(first["receipt_sha256"], scanner.receipt_hash(first))
        self.assertEqual(
            first["trust_bindings"]["scanner_blob_sha256"],
            _sha256(SCANNER_PATH.read_bytes()),
        )
        self.assertEqual(
            first["trust_bindings"]["baseline_blob_sha256"], _sha256(_baseline())
        )
        paths = {row["path"] for row in first["surfaces"]}
        self.assertIn(f"snapshot/{OKF_PATH}", paths)
        self.assertIn(f"tar/{OKF_PATH}", paths)
        rendered = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(str(fixture.root), rendered)
        self.assertNotIn("timestamp", rendered.lower())

    def test_unpacked_git_blob_with_provider_token_is_scanned_and_cannot_be_waived(
        self,
    ) -> None:
        fixture = PublicScanFixture(self)
        fixture.write_source(
            "private/unpackaged.txt", f"credential={PROVIDER_SAMPLE}\n".encode()
        )
        fixture.write_source("tests/private-key-fixture.pem", PEM_SAMPLE)
        fixture.commit("add scanner credential negatives")

        receipt = fixture.scan()

        self.assertFalse(receipt["passed"])
        provider = next(
            finding
            for finding in receipt["unwaived_findings"]
            if finding["path"] == "git/final/private/unpackaged.txt"
        )
        private_key = next(
            finding
            for finding in receipt["unwaived_findings"]
            if finding["path"] == "git/final/tests/private-key-fixture.pem"
        )
        self.assertIn("provider_token", provider["non_waivable_reasons"])
        self.assertIn("private_key", private_key["non_waivable_reasons"])
        self.assertFalse(provider["synthetic_fixture_eligible"])
        self.assertFalse(private_key["synthetic_fixture_eligible"])
        self.assertFalse(
            any(
                finding["path"].startswith("snapshot/private/")
                for finding in receipt["unwaived_findings"]
            )
        )

        reviewed = _baseline(
            [
                {
                    "path": provider["path"],
                    "sha256": provider["sha256"],
                    "finding_kinds": provider["finding_kinds"],
                    "reason": "detector_literal",
                }
            ]
        )
        with self.assertRaises(scanner.PublicScanError) as forbidden:
            fixture.scan(baseline_bytes=reviewed)
        self.assertEqual(forbidden.exception.code, "E_PUBLIC_SCAN_BASELINE_REASON")

    def test_intermediate_blob_and_raw_commit_message_survive_later_deletion(self) -> None:
        fixture = PublicScanFixture(self)
        fixture.write_source(
            "scratch/intermediate.txt", b"token=intermediate-secret-value\n"
        )
        introduced_at = fixture.commit("token=intermediate-message-secret")
        object_id = fixture._git("rev-parse", f"{introduced_at}:scratch/intermediate.txt")
        fixture.remove_source("scratch/intermediate.txt")
        fixture.commit("remove intermediate file")

        receipt = fixture.scan()

        paths = {finding["path"] for finding in receipt["unwaived_findings"]}
        blob_path = f"git/history/blobs/{object_id}/scratch/intermediate.txt"
        commit_surface = next(
            row
            for row in receipt["surfaces"]
            if row.get("source_kind") == "git_commit_raw"
            and row.get("object_id") == introduced_at
        )
        self.assertIn(blob_path, paths)
        self.assertIn(commit_surface["path"], paths)
        self.assertNotIn("git/final/scratch/intermediate.txt", paths)
        surface = next(row for row in receipt["surfaces"] if row["path"] == blob_path)
        self.assertEqual(surface["object_id"], object_id)
        self.assertIn(
            {"commit": introduced_at, "path": "scratch/intermediate.txt"},
            surface["appearances"],
        )

    def test_reviewed_baseline_is_exact_and_one_byte_change_fails_closed(self) -> None:
        fixture = PublicScanFixture(self)
        relative = "tests/synthetic-fixture.txt"
        fixture.write_snapshot(relative, b"token=dummy-fixture-secret\n")
        fixture.rebuild_tar()

        candidate_receipt = fixture.scan()
        candidates = [
            row
            for row in candidate_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(b"token=dummy-fixture-secret\n")
        ]
        self.assertEqual({row["path"] for row in candidates}, {
            f"snapshot/{relative}", f"tar/{relative}"
        })
        self.assertTrue(all(row["waivable"] for row in candidates))
        self.assertTrue(
            all("synthetic_fixture" in row["allowed_reasons"] for row in candidates)
        )
        reviewed = _baseline(
            [
                {
                    "path": candidate["path"],
                    "sha256": candidate["sha256"],
                    "finding_kinds": candidate["finding_kinds"],
                    "reason": "synthetic_fixture",
                }
                for candidate in candidates
            ]
        )
        accepted = fixture.scan(baseline_bytes=reviewed)
        self.assertTrue(accepted["passed"])
        self.assertTrue(
            all(row["reason"] == "synthetic_fixture" for row in accepted["waived_findings"])
        )

        fixture.write_snapshot(relative, b"token=dummy-fixture-secret-X\n")
        fixture.rebuild_tar()
        changed = fixture.scan(baseline_bytes=reviewed)

        self.assertFalse(changed["passed"])
        self.assertTrue(
            any(error.startswith("unwaived_finding:snapshot/tests/") for error in changed["errors"])
        )
        self.assertIn(
            f"stale_baseline_assertion:{candidates[0]['path']}:{candidates[0]['sha256']}",
            changed["errors"],
        )

    def test_tar_generated_okf_is_scanned_independently_from_snapshot(self) -> None:
        fixture = PublicScanFixture(self)
        fixture.rebuild_tar(
            {OKF_PATH: b'{"token":"generated-only-secret-value"}\n'}
        )

        with self.assertRaises(scanner.PublicScanError) as mismatch:
            fixture.scan()
        self.assertEqual(
            mismatch.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

    def test_tag_title_and_body_are_nonwaivable_public_surfaces(self) -> None:
        fixture = PublicScanFixture(self)

        receipt = fixture.scan(
            tag_message="token=bad-tag-message-secret",
            release_title=f"Release {PROVIDER_SAMPLE}",
            release_body=(
                PEM_SAMPLE.decode("utf-8")
                + "workspace=/"
                + "Users/Rou/private\n"
            ),
        )

        by_path = {row["path"]: row for row in receipt["unwaived_findings"]}
        self.assertFalse(receipt["passed"])
        for path in ("release/tag-message", "release/title", "release/body"):
            self.assertIn(path, by_path)
            self.assertIn("unwaivable_surface", by_path[path]["non_waivable_reasons"])

    def test_baseline_schema_rejects_public_surfaces_and_fake_synthetic_scope(self) -> None:
        digest = "a" * 64
        rows = (
            {
                "path": "git/final/README.md",
                "sha256": digest,
                "finding_kinds": ["secret"],
                "reason": "detector_literal",
            },
            {
                "path": "release/body",
                "sha256": digest,
                "finding_kinds": ["secret"],
                "reason": "detector_literal",
            },
            {
                "path": "snapshot/src/application.py",
                "sha256": digest,
                "finding_kinds": ["secret"],
                "reason": "synthetic_fixture",
            },
        )
        for row in rows:
            with self.subTest(path=row["path"]), self.assertRaises(
                scanner.PublicScanError
            ):
                scanner.validate_baseline(scanner.load_baseline(_baseline([row])))

    def test_git_replace_grafts_shallow_partial_and_environment_fail_closed(self) -> None:
        replacement = PublicScanFixture(self)
        candidate = replacement._git("rev-parse", "HEAD")
        replacement._git("replace", candidate, replacement.base_commit)
        with self.assertRaises(scanner.PublicScanError) as replaced:
            replacement.scan()
        self.assertEqual(replaced.exception.code, "E_PUBLIC_SCAN_GIT_REPLACE")

        blob_replacement = PublicScanFixture(self)
        candidate_blob = blob_replacement._git("rev-parse", "HEAD:src/app.txt")
        safe_blob = blob_replacement._git("rev-parse", "HEAD:README.md")
        blob_replacement._git("replace", candidate_blob, safe_blob)
        with self.assertRaises(scanner.PublicScanError) as replaced_blob:
            blob_replacement.scan()
        self.assertEqual(replaced_blob.exception.code, "E_PUBLIC_SCAN_GIT_REPLACE")

        grafted = PublicScanFixture(self)
        common_value = grafted._git("rev-parse", "--git-common-dir")
        common = Path(common_value)
        if not common.is_absolute():
            common = grafted.source / common
        (common / "info").mkdir(parents=True, exist_ok=True)
        (common / "info" / "grafts").write_text(
            grafted._git("rev-parse", "HEAD") + "\n", encoding="utf-8"
        )
        with self.assertRaises(scanner.PublicScanError) as grafts:
            grafted.scan()
        self.assertEqual(grafts.exception.code, "E_PUBLIC_SCAN_GIT_GRAFTS")

        shallow = PublicScanFixture(self)
        git_dir_value = shallow._git("rev-parse", "--git-dir")
        git_dir = Path(git_dir_value)
        if not git_dir.is_absolute():
            git_dir = shallow.source / git_dir
        (git_dir / "shallow").write_text(
            shallow.base_commit + "\n", encoding="ascii"
        )
        with self.assertRaises(scanner.PublicScanError) as shallow_error:
            shallow.scan()
        self.assertEqual(shallow_error.exception.code, "E_PUBLIC_SCAN_GIT_SHALLOW")

        partial = PublicScanFixture(self)
        partial._git("config", "remote.origin.promisor", "true")
        with self.assertRaises(scanner.PublicScanError) as partial_error:
            partial.scan()
        self.assertEqual(partial_error.exception.code, "E_PUBLIC_SCAN_GIT_PARTIAL")

        partial_extension = PublicScanFixture(self)
        partial_extension._git("config", "core.repositoryformatversion", "1")
        partial_extension._git("config", "extensions.partialClone", "origin")
        with self.assertRaises(scanner.PublicScanError) as extension_error:
            partial_extension.scan()
        self.assertEqual(extension_error.exception.code, "E_PUBLIC_SCAN_GIT_PARTIAL")

        environment = PublicScanFixture(self)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(environment.source / ".git")}):
            with self.assertRaises(scanner.PublicScanError) as environment_error:
                environment.scan()
        self.assertEqual(environment_error.exception.code, "E_PUBLIC_SCAN_GIT_ENV")

    def test_detector_is_loaded_from_frozen_candidate_and_digest_bound(self) -> None:
        fixture = PublicScanFixture(self)
        with self.assertRaises(scanner.PublicScanError) as mismatch:
            fixture.scan(expected_detector_digest="0" * 64)
        self.assertEqual(mismatch.exception.code, "E_PUBLIC_SCAN_DETECTOR")

        fixture.write_source(
            "private/credential.txt", f"credential={PROVIDER_SAMPLE}\n".encode()
        )
        fixture.commit("add frozen detector negative")
        fixture.write_source(
            "scripts/v23/v236_security.py",
            b"import re\nHOME_PATH_RE=PRIVATE_KEY_RE=COMMON_TOKEN_RE=re.compile('never')\ndef contains_secret(text): return False\n",
        )
        receipt = fixture.scan()
        self.assertFalse(receipt["passed"])
        self.assertTrue(
            any(
                row["path"] == "git/final/private/credential.txt"
                and "provider_token" in row["non_waivable_reasons"]
                for row in receipt["unwaived_findings"]
            )
        )
        self.assertEqual(
            receipt["trust_bindings"]["detector_blob_sha256"],
            _sha256(DETECTOR_SOURCE),
        )

    def test_git_paths_intermediate_renames_and_gitlinks_are_covered(self) -> None:
        fixture = PublicScanFixture(self)
        token_path = f"private/{PROVIDER_SAMPLE}.txt"
        fixture.write_source(token_path, b"safe path payload\n")
        fixture.write_source(".netrc", b"machine example.invalid login nobody\n")
        fixture.commit("add sensitive public paths")
        receipt = fixture.scan()
        by_path = {row["path"]: row for row in receipt["unwaived_findings"]}
        token_finding = by_path[f"git/final/{token_path}"]
        self.assertIn("path", token_finding["finding_sources"])
        self.assertIn("provider_token", token_finding["non_waivable_reasons"])
        netrc = by_path["git/final/.netrc"]
        self.assertIn("private_provenance_path", netrc["non_waivable_reasons"])

        renamed = PublicScanFixture(self)
        intermediate_path = f"private/{PROVIDER_SAMPLE}.txt"
        (renamed.source / "private").mkdir()
        renamed._git("mv", "README.md", intermediate_path)
        intermediate_commit = renamed.commit("temporary sensitive path")
        renamed._git("mv", intermediate_path, "README.md")
        renamed.commit("restore safe path")
        renamed_receipt = renamed.scan()
        self.assertTrue(
            any(
                row["path"].startswith("git/history/tree-paths/")
                and row.get("sha256")
                == _sha256(
                    (
                        "100644\0"
                        + renamed._git(
                            "rev-parse", f"{intermediate_commit}:{intermediate_path}"
                        )
                        + "\0"
                        + intermediate_path
                    ).encode("utf-8")
                )
                and "provider_token" in row["non_waivable_reasons"]
                for row in renamed_receipt["unwaived_findings"]
            )
        )

        gitlink = PublicScanFixture(self)
        gitlink._git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{gitlink.base_commit},vendor/submodule",
        )
        gitlink._git("commit", "--no-gpg-sign", "-m", "add forbidden gitlink")
        with self.assertRaises(scanner.PublicScanError) as gitlink_error:
            gitlink.scan()
        self.assertEqual(gitlink_error.exception.code, "E_PUBLIC_SCAN_GITLINK")

    def test_baseline_never_waives_provider_or_real_credentials(self) -> None:
        provider = PublicScanFixture(self)
        provider_data = f"credential={PROVIDER_SAMPLE} fixture\n".encode()
        provider.write_source("tests/synthetic-fixture.txt", provider_data)
        provider.commit("add provider-shaped fixture")
        provider_receipt = provider.scan()
        provider_rows = [
            row
            for row in provider_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(provider_data)
        ]
        self.assertTrue(provider_rows)
        self.assertTrue(all(row["waivable"] is False for row in provider_rows))
        attempted_provider_baseline = _baseline(
            [
                {
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "finding_kinds": row["finding_kinds"],
                    "reason": "synthetic_fixture",
                }
                for row in provider_rows
            ]
        )
        provider_rescan = provider.scan(
            baseline_bytes=attempted_provider_baseline
        )
        self.assertFalse(provider_rescan["passed"])
        self.assertFalse(provider_rescan["waived_findings"])

        credential = PublicScanFixture(self)
        credential_data = b"password=actual-production-password-value\n"
        credential.write_source("tests/credential-fixture.txt", credential_data)
        credential.commit("add credential negative")
        credential_receipt = credential.scan()
        credential_rows = [
            row
            for row in credential_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(credential_data)
        ]
        self.assertTrue(credential_rows)
        self.assertTrue(
            all("credential" in row.get("non_waivable_reasons", []) for row in credential_receipt["unwaived_findings"] if row["sha256"] == _sha256(credential_data))
        )
        attempted_credential_baseline = _baseline(
            [
                {
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "finding_kinds": row["finding_kinds"],
                    "reason": "synthetic_fixture",
                }
                for row in credential_rows
            ]
        )
        credential_rescan = credential.scan(
            baseline_bytes=attempted_credential_baseline
        )
        self.assertFalse(credential_rescan["passed"])
        self.assertFalse(credential_rescan["waived_findings"])

    def test_placeholder_home_only_allows_generic_identities(self) -> None:
        fixture = PublicScanFixture(self)
        relative = "examples/placeholder-home.txt"
        generic = b"workspace=/Users/example/project\n"
        fixture.write_snapshot(relative, generic)
        fixture.rebuild_tar()
        receipt = fixture.scan()
        rows = [
            row
            for row in receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(generic)
        ]
        self.assertEqual(len(rows), 2)
        reviewed = _baseline(
            [
                {
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "finding_kinds": row["finding_kinds"],
                    "reason": "placeholder_home",
                }
                for row in rows
            ]
        )
        self.assertTrue(fixture.scan(baseline_bytes=reviewed)["passed"])

        private = b"workspace=/" + b"Users/Rou/private\n"
        fixture.write_snapshot(relative, private)
        fixture.rebuild_tar()
        private_receipt = fixture.scan()
        private_rows = [
            row
            for row in private_receipt["baseline_candidate_rows"]
            if row["sha256"] == _sha256(private)
        ]
        attempted = _baseline(
            [
                {
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "finding_kinds": row["finding_kinds"],
                    "reason": "placeholder_home",
                }
                for row in private_rows
            ]
        )
        rejected = fixture.scan(baseline_bytes=attempted)
        self.assertFalse(rejected["passed"])
        self.assertFalse(rejected["waived_findings"])

    def test_snapshot_tar_identity_modes_and_membership_are_exact(self) -> None:
        content = PublicScanFixture(self)
        content.rebuild_tar({"README.md": b"different tar content\n"})
        with self.assertRaises(scanner.PublicScanError) as content_error:
            content.scan()
        self.assertEqual(
            content_error.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

        mode = PublicScanFixture(self)
        (mode.snapshot / "README.md").chmod(0o755)
        with self.assertRaises(scanner.PublicScanError) as mode_error:
            mode.scan()
        self.assertEqual(
            mode_error.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH"
        )

        membership = PublicScanFixture(self)
        membership.write_snapshot("extra.txt", b"snapshot only\n")
        with self.assertRaises(scanner.PublicScanError) as membership_error:
            membership.scan()
        self.assertEqual(
            membership_error.exception.code,
            "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH",
        )

    def test_snapshot_membership_race_fails_closed(self) -> None:
        fixture = PublicScanFixture(self)
        original = scanner._read_regular_file
        mutated = False

        def racing(path: Path, *, max_bytes: int, code: str) -> bytes:
            nonlocal mutated
            data = original(path, max_bytes=max_bytes, code=code)
            if (
                fixture.snapshot.resolve() in path.resolve().parents
                and not mutated
            ):
                mutated = True
                fixture.write_snapshot("late-added.txt", b"late\n")
            return data

        with mock.patch.object(scanner, "_read_regular_file", side_effect=racing):
            with self.assertRaises(scanner.PublicScanError) as changed:
                fixture.scan()
        self.assertEqual(changed.exception.code, "E_PUBLIC_SCAN_SNAPSHOT_CHANGED")

    def test_tar_and_gzip_metadata_must_be_canonical(self) -> None:
        metadata = PublicScanFixture(self)
        metadata._write_tar(
            metadata._snapshot_entries(), uname=PROVIDER_SAMPLE
        )
        metadata._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as metadata_error:
            metadata.scan()
        self.assertEqual(metadata_error.exception.code, "E_PUBLIC_SCAN_TAR_METADATA")

        gzip_header = PublicScanFixture(self)
        gzip_header._write_tar(
            gzip_header._snapshot_entries(), gzip_filename="private-build-path.tar"
        )
        gzip_header._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as gzip_error:
            gzip_header.scan()
        self.assertEqual(gzip_error.exception.code, "E_PUBLIC_SCAN_GZIP_METADATA")

        ordering = PublicScanFixture(self)
        ordering._write_tar(reversed(ordering._snapshot_entries()))
        ordering._refresh_manifests()
        with self.assertRaises(scanner.PublicScanError) as order_error:
            ordering.scan()
        self.assertEqual(order_error.exception.code, "E_PUBLIC_SCAN_TAR_CANONICAL")

    def test_snapshot_and_tar_paths_are_scanned_as_public_surfaces(self) -> None:
        fixture = PublicScanFixture(self)
        relative = f"tests/{PROVIDER_SAMPLE}.txt"
        fixture.write_snapshot(relative, b"safe content\n")
        fixture.rebuild_tar()
        receipt = fixture.scan()
        paths = {row["path"]: row for row in receipt["unwaived_findings"]}
        for surface in (f"snapshot/{relative}", f"tar/{relative}"):
            self.assertIn(surface, paths)
            self.assertIn("path", paths[surface]["finding_sources"])
            self.assertIn("provider_token", paths[surface]["non_waivable_reasons"])

    def test_tar_rejects_traversal_link_device_duplicate_and_limits(self) -> None:
        fixture = PublicScanFixture(self)
        generated = (OKF_PATH, b'{"status":"generated"}\n', "file")
        cases = {
            "traversal": (
                [generated, ("../escape.txt", b"escape\n", "file")],
                "E_PUBLIC_SCAN_TAR_PATH",
            ),
            "symlink": (
                [generated, ("docs/link", b"../../private", "symlink")],
                "E_PUBLIC_SCAN_TAR_TYPE",
            ),
            "device": (
                [generated, ("docs/device", b"", "char-device")],
                "E_PUBLIC_SCAN_TAR_TYPE",
            ),
            "duplicate": (
                [
                    generated,
                    ("docs/repeated.txt", b"first\n", "file"),
                    ("docs/repeated.txt", b"second\n", "file"),
                ],
                "E_PUBLIC_SCAN_TAR_DUPLICATE",
            ),
            "path-limit": (
                [generated, ("x" * 241, b"too long\n", "file")],
                "E_PUBLIC_SCAN_TAR_LIMIT",
            ),
        }
        for name, (entries, expected_code) in cases.items():
            fixture.write_custom_tar(entries)
            with self.subTest(name=name), self.assertRaises(
                scanner.PublicScanError
            ) as caught:
                fixture.scan()
            self.assertEqual(caught.exception.code, expected_code)


if __name__ == "__main__":
    unittest.main()
