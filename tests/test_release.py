"""Tests for tools/release.py: build, verify, notes and check-tag.

Every test builds from its own temporary git repository (or plain directory),
never from the real working tree.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "release.py"
PIPE = subprocess.PIPE


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load("goal_teams_release_under_test", TOOL)
ed25519 = _load("goal_teams_release_ed25519_under_test", ROOT / "tools" / "ed25519_verify.py")

HAS_GIT = shutil.which("git") is not None
COMMIT_EPOCH = 1790000000
VERSION = "3.0.0"
TOP = "goal-teams-" + VERSION
TARBALL = TOP + ".tar.gz"
SKILL = "plugins/goal-teams/skills/goal-teams/SKILL.md"
GT = "plugins/goal-teams/skills/goal-teams/scripts/gt.py"

CHANGELOG = """# Changelog

## V3.0.0 — 2026-10-18

### 新增
- 发布工具 `tools/release.py`。

```markdown
## not a heading inside a fence
```

## V3.0 — 2026-10-01

- short form

## V2.68 Published — 2026-09-08

- old
"""

FILES: Dict[str, bytes] = {
    ".claude-plugin/marketplace.json": b'{"name": "goal-teams", "plugins": []}\n',
    "AGENTS.md": b"# repository only, never shipped\n",
    "CHANGELOG.md": CHANGELOG.encode("utf-8"),
    "LICENSE": b"MIT License\n",
    "README.en.md": b"# Goal Teams\n",
    "README.md": "# Goal Teams 说明\n".encode("utf-8"),
    "VERSION": b"3.0.0\n",
    "plugins/goal-teams/.claude-plugin/plugin.json": b'{"name": "goal-teams"}\n',
    "plugins/goal-teams/agents/goal_backend.md": b"---\nname: goal_backend\n---\n",
    "plugins/goal-teams/evals/cases.json": b"[]\n",
    GT: b"print('gt')\n",
    SKILL: "# Goal Teams\n\n我是 Goal Teams Lead V3.0。\n".encode("utf-8"),
    "tools/install.py": b"print('install')\n",
    "tools/release.py": b"# repository only, never shipped\n",
}
EXECUTABLE = (GT, "tools/install.py")
SHIPPED = sorted(path for path in FILES if path not in ("AGENTS.md", "tools/release.py"))

# RFC 8032 section 7.1, tests 1-3: (secret seed, public key, message, signature).
RFC8032 = (
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
)
SEED = bytes(range(32))
OTHER_SEED = bytes(range(1, 33))

Member = Tuple[tarfile.TarInfo, Optional[bytes]]


# ------------------------------------------------------------------- helpers


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ed25519_sign(seed: bytes, message: bytes) -> Tuple[bytes, bytes]:
    """Test-only RFC 8032 signer built on the verifier's curve arithmetic."""

    digest = hashlib.sha512(seed).digest()
    scalar = (int.from_bytes(digest[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
    public = ed25519._encode_point(ed25519._scalar_mult(ed25519._BASE, scalar))
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % ed25519._L
    encoded_r = ed25519._encode_point(ed25519._scalar_mult(ed25519._BASE, nonce))
    challenge = int.from_bytes(
        hashlib.sha512(encoded_r + public + message).digest(), "little"
    ) % ed25519._L
    s = (nonce + challenge * scalar) % ed25519._L
    return public, encoded_r + s.to_bytes(32, "little")


def pem(public: bytes) -> bytes:
    der = bytes.fromhex("302a300506032b6570032100") + public
    return b"-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(der) + b"\n-----END PUBLIC KEY-----\n"


def environment(base: Path) -> Dict[str, str]:
    """Isolate git and the tool from the caller's git config and environment."""

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_") and key.upper() != "SOURCE_DATE_EPOCH"
    }
    config = base / "gitconfig"
    if not config.exists():
        config.write_bytes(b"")
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(config),
        GIT_CEILING_DIRECTORIES=str(base),
        GIT_AUTHOR_DATE=f"{COMMIT_EPOCH} +0000",
        GIT_COMMITTER_DATE=f"{COMMIT_EPOCH} +0000",
    )
    return env


def run_git(env: Dict[str, str], cwd: Path, *args: str, stdin: Optional[bytes] = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, input=stdin, stdout=PIPE, stderr=PIPE
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace')}")
    return proc.stdout.decode("utf-8", "replace").strip()


def commit(env: Dict[str, str], repo: Path, message: str = "commit") -> None:
    run_git(
        env, repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", message,
    )


def write_tree(root: Path, files: Dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if rel in EXECUTABLE:
            path.chmod(0o755)


def make_repo(env: Dict[str, str], repo: Path, files: Dict[str, bytes] = FILES) -> Path:
    write_tree(repo, files)
    run_git(env, repo, "init", "-q")
    run_git(env, repo, "config", "core.autocrlf", "false")
    run_git(env, repo, "add", "-A")
    for rel in EXECUTABLE:
        if rel in files:
            run_git(env, repo, "update-index", "--chmod=+x", rel)
    commit(env, repo, "init")
    return repo


def run_tool(env: Dict[str, str], *args: str, **extra_env: str) -> Tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args], env=dict(env, **extra_env), stdout=PIPE, stderr=PIPE
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def read_members(tar_path: Path) -> List[Member]:
    with tarfile.open(tar_path, "r:gz") as archive:
        return [
            (member, archive.extractfile(member).read() if member.isfile() else None)
            for member in archive.getmembers()
        ]


def new_member(
    name: str, kind: bytes = tarfile.REGTYPE, data: bytes = b"", mode: int = 0o644, linkname: str = ""
) -> Member:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = mode
    info.linkname = linkname
    info.mtime = COMMIT_EPOCH
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    return info, (data if kind == tarfile.REGTYPE else None)


def tar_stream(members: List[Member], global_pax: Optional[Dict[str, str]] = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(
        fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT, pax_headers=global_pax
    ) as archive:
        for info, data in members:
            archive.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def reseal(dist: Path, files: Optional[list] = None) -> None:
    """Make release.json and SHA256SUMS consistent with the (tampered) tarball,
    as anyone without the signing key can."""

    tarball = (dist / TARBALL).read_bytes()
    manifest = json.loads((dist / "release.json").read_bytes())
    manifest["tarball"].update(size=len(tarball), sha256=sha(tarball))
    if files is not None:
        manifest["files"] = files
    if "asset_set_id" in manifest:  # a forger who rewrites the manifest can recompute this too
        manifest["asset_set_id"] = release.asset_set_id(manifest["files"], manifest["tarball"])
    data = (json.dumps(manifest, indent=2) + "\n").encode("ascii")
    (dist / "release.json").write_bytes(data)
    sums = f"{sha(tarball)}  {TARBALL}\n{sha(data)}  release.json\n"
    (dist / "SHA256SUMS").write_bytes(sums.encode("ascii"))


def retar(dist: Path, mutate: Callable[[List[Member]], List[Member]], files: Optional[list] = None) -> None:
    members = mutate(read_members(dist / TARBALL))
    (dist / TARBALL).write_bytes(gzip.compress(tar_stream(members), mtime=0))
    reseal(dist, files)


class ReleaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name).resolve()
        self.env = environment(self.tmp)

    def git(self, cwd: Path, *args: str, stdin: Optional[bytes] = None) -> str:
        return run_git(self.env, cwd, *args, stdin=stdin)

    def make_repo(self, name: str = "repo", files: Dict[str, bytes] = FILES) -> Path:
        return make_repo(self.env, self.tmp / name, files)

    def run_tool(self, *args: str, **extra_env: str) -> Tuple[int, str, str]:
        return run_tool(self.env, *args, **extra_env)

    def build(self, root: Path, out: Optional[Path] = None, *extra: str, **extra_env: str) -> Path:
        out = out or self.tmp / "dist"
        code, stdout, stderr = self.run_tool(
            "build", "--root", str(root), "--out", str(out), *extra, **extra_env
        )
        self.assertEqual(code, 0, stdout + stderr)
        return out

    def build_fails(self, root: Path, *extra: str, **extra_env: str) -> str:
        code, stdout, stderr = self.run_tool(
            "build", "--root", str(root), "--out", str(self.tmp / "refused"), *extra, **extra_env
        )
        self.assertEqual(code, 1, stdout + stderr)
        return stderr

    def verify(self, directory: Path, *extra: str) -> Tuple[int, str]:
        # --root points at a directory without keys/, so no default key is found.
        code, stdout, stderr = self.run_tool("verify", str(directory), "--root", str(self.tmp), *extra)
        return code, stdout + stderr


# --------------------------------------------------------------------- build


@unittest.skipUnless(HAS_GIT, "git is required")
class BuildFromGitTests(ReleaseTestCase):
    def test_build_writes_the_documented_layout(self) -> None:
        repo = self.make_repo()
        (repo / "plugins/goal-teams/untracked.md").write_bytes(b"not committed\n")
        dist = self.tmp / "dist"
        code, stdout, stderr = self.run_tool("build", "--root", str(repo), "--out", str(dist))
        self.assertEqual(code, 0, stdout + stderr)
        self.assertIn("MIGRATION.md: not found; skipped", stderr)
        self.assertIn("plugins/goal-teams/untracked.md: not tracked by git", stderr)
        self.assertEqual(sorted(p.name for p in dist.iterdir()), ["SHA256SUMS", TARBALL, "release.json"])

        tarball = (dist / TARBALL).read_bytes()
        self.assertEqual(tarball[:8], b"\x1f\x8b\x08\x00\x00\x00\x00\x00")  # no file name, mtime 0
        members = read_members(dist / TARBALL)
        names = [member.name for member, _ in members]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], TOP)
        files = {m.name[len(TOP) + 1:]: (m, data) for m, data in members if m.isfile()}
        directories = {m.name for m, _ in members if m.isdir()}
        self.assertEqual(sorted(files), SHIPPED)
        self.assertEqual(len(members), len(files) + len(directories))
        self.assertIn(TOP + "/plugins/goal-teams/skills/goal-teams/scripts", directories)
        for member, _ in members:
            self.assertEqual(
                (member.uid, member.gid, member.uname, member.gname, member.mtime),
                (0, 0, "", "", COMMIT_EPOCH),
            )
            if member.isdir():
                self.assertEqual(member.mode, 0o755, member.name)
        for rel, (member, data) in files.items():
            self.assertEqual(data, FILES[rel], rel)
            self.assertEqual(member.mode, 0o755 if rel in EXECUTABLE else 0o644, rel)

        manifest_bytes = (dist / "release.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(list(manifest), ["name", "version", "commit", "tree", "files", "tarball", "asset_set_id", "build"])
        self.assertEqual(manifest["asset_set_id"], release.asset_set_id(manifest["files"], manifest["tarball"]))
        self.assertEqual(sorted(manifest["build"]), ["platform", "python", "tool"])
        self.assertEqual((manifest["name"], manifest["version"]), ("goal-teams", VERSION))
        self.assertEqual(manifest["commit"], self.git(repo, "rev-parse", "HEAD"))
        self.assertEqual(manifest["tree"], self.git(repo, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(
            manifest["files"],
            [{"path": p, "size": len(FILES[p]), "sha256": sha(FILES[p])} for p in SHIPPED],
        )
        self.assertEqual(manifest["tarball"], {"name": TARBALL, "size": len(tarball), "sha256": sha(tarball)})
        self.assertEqual(
            (dist / "SHA256SUMS").read_bytes(),
            f"{sha(tarball)}  {TARBALL}\n{sha(manifest_bytes)}  release.json\n".encode("ascii"),
        )

    def test_build_is_byte_identical_twice_and_from_a_clone(self) -> None:
        repo = self.make_repo()
        first = self.build(repo, self.tmp / "one")
        second = self.build(repo, self.tmp / "two")
        clone = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", str(repo), str(clone))
        os.utime(clone / SKILL, (1, 1))  # working-tree times and paths must not leak
        third = self.build(clone, self.tmp / "three")
        for name in ("SHA256SUMS", TARBALL, "release.json"):
            data = (first / name).read_bytes()
            self.assertEqual((second / name).read_bytes(), data, name)
            self.assertEqual((third / name).read_bytes(), data, name)

    def test_source_date_epoch_sets_member_times(self) -> None:
        repo = self.make_repo()
        dist = self.build(repo, None, SOURCE_DATE_EPOCH="1700000000")
        self.assertEqual({m.mtime for m, _ in read_members(dist / TARBALL)}, {1700000000})
        self.assertIn("SOURCE_DATE_EPOCH", self.build_fails(repo, SOURCE_DATE_EPOCH="yesterday"))

    def test_input_that_differs_from_head_is_refused_unless_allowed(self) -> None:
        repo = self.make_repo()
        (repo / SKILL).write_bytes(b"# changed\n")
        stderr = self.build_fails(repo)
        self.assertIn(SKILL, stderr)
        self.assertIn("--allow-dirty", stderr)
        self.assertFalse((self.tmp / "refused").exists())

        dist = self.build(repo, None, "--allow-dirty")
        manifest = json.loads((dist / "release.json").read_bytes())
        self.assertEqual((manifest["commit"], manifest["tree"]), (None, None))
        contents = {m.name: data for m, data in read_members(dist / TARBALL)}
        self.assertEqual(contents[f"{TOP}/{SKILL}"], b"# changed\n")

    def test_missing_required_inputs_fail(self) -> None:
        for removed, message in (
            ("tools/install.py", "tools/install.py is required"),
            ("plugins", "plugins/goal-teams/ is required"),
        ):
            with self.subTest(removed=removed):
                repo = self.make_repo("repo-" + removed.replace("/", "-"))
                self.git(repo, "rm", "-r", "-q", removed)
                commit(self.env, repo, "remove")
                self.assertIn(message, self.build_fails(repo))

    def test_names_that_differ_only_by_case_are_rejected(self) -> None:
        (self.tmp / "CaseProbe").write_bytes(b"")
        if (self.tmp / "caseprobe").exists():
            self.skipTest("case-insensitive file system")
        files = dict(FILES)
        files["plugins/goal-teams/Notes.md"] = b"a\n"
        files["plugins/goal-teams/notes.md"] = b"b\n"
        self.assertIn("differ only by letter case", self.build_fails(self.make_repo(files=files)))

    def test_committed_symlink_is_rejected(self) -> None:
        repo = self.make_repo()
        blob = self.git(repo, "hash-object", "-w", "--stdin", stdin=b"SKILL.md")
        self.git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},plugins/goal-teams/link.md")
        commit(self.env, repo, "symlink")
        self.assertIn("plugins/goal-teams/link.md: symlinks are not allowed", self.build_fails(repo))

    def test_output_directory_holds_only_release_assets(self) -> None:
        repo = self.make_repo()
        out = self.tmp / "dist"
        out.mkdir()
        (out / "old.txt").write_bytes(b"x")
        code, _, stderr = self.run_tool("build", "--root", str(repo), "--out", str(out))
        self.assertEqual(code, 1)
        self.assertIn("already holds other files (old.txt)", stderr)
        (out / "old.txt").unlink()
        self.build(repo, out)
        (out / "SHA256SUMS.sig").write_bytes(b"\0" * 64)
        code, _, stderr = self.run_tool("build", "--root", str(repo), "--out", str(out))
        self.assertEqual(code, 0, stderr)
        self.assertIn("removed the stale SHA256SUMS.sig", stderr)
        self.assertFalse((out / "SHA256SUMS.sig").exists())

    def test_version_override_and_invalid_versions(self) -> None:
        repo = self.make_repo()
        code, _, stderr = self.run_tool(
            "build", "--root", str(repo), "--out", str(self.tmp / "rc"), "--version", "3.1.0-rc.1"
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("differs from VERSION", stderr)
        self.assertTrue((self.tmp / "rc" / "goal-teams-3.1.0-rc.1.tar.gz").is_file())
        for bad in ("../x", "v3.0.0", "3", "3.0.0/x"):
            with self.subTest(version=bad):
                self.assertIn("must look like 2.7.0", self.build_fails(repo, "--version", bad))
        legacy = self.make_repo("legacy", dict(FILES, VERSION=b"V2.68\n"))
        self.assertIn("must look like 2.7.0", self.build_fails(legacy))


class BuildWithoutGitTests(ReleaseTestCase):
    def test_plain_directory_is_walked_with_exclusions(self) -> None:
        plain = self.tmp / "plain"
        write_tree(plain, FILES)
        write_tree(plain, {
            "plugins/goal-teams/skills/goal-teams/scripts/__pycache__/gt.cpython-313.pyc": b"\0",
            "plugins/goal-teams/.DS_Store": b"\0",
            "plugins/goal-teams/evals/results/run-1.json": b"{}\n",
            "plugins/goal-teams/stray.pyc": b"\0",
        })
        code, stdout, stderr = self.run_tool("build", "--root", str(plain), "--out", str(self.tmp / "dist"))
        self.assertEqual(code, 0, stdout + stderr)
        self.assertIn("no git", stdout)
        manifest = json.loads((self.tmp / "dist" / "release.json").read_bytes())
        self.assertEqual([item["path"] for item in manifest["files"]], SHIPPED)
        self.assertEqual((manifest["commit"], manifest["tree"]), (None, None))
        members = read_members(self.tmp / "dist" / TARBALL)
        self.assertEqual({member.mtime for member, _ in members}, {0})
        if os.name != "nt":  # Windows has no executable bit on disk
            modes = {m.name[len(TOP) + 1:]: m.mode for m, _ in members if m.isfile()}
            self.assertEqual((modes[GT], modes["LICENSE"]), (0o755, 0o644))

    @unittest.skipUnless(HAS_GIT, "git is required")
    def test_unreadable_git_metadata_is_an_error_not_a_silent_fallback(self) -> None:
        plain = self.tmp / "plain"
        write_tree(plain, FILES)
        (plain / ".git").write_bytes(b"gitdir: does-not-exist\n")
        self.assertIn("has .git but git cannot read it", self.build_fails(plain))

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra privileges on Windows")
    def test_symlink_on_disk_is_rejected(self) -> None:
        plain = self.tmp / "plain"
        write_tree(plain, FILES)
        os.symlink("SKILL.md", plain / "plugins/goal-teams/skills/goal-teams/link.md")
        self.assertIn("symlinks are not allowed", self.build_fails(plain))

    def test_path_rules(self) -> None:
        for bad in ("", "/abs", "a/../b", "a//b", "./a", "a/", "a\\b", "C:/x", "a/\x1b[31m"):
            with self.subTest(path=bad):
                self.assertIsNotNone(release.path_problem(bad))
        for good in (SKILL, "说明.md", ".claude-plugin/marketplace.json"):
            self.assertIsNone(release.path_problem(good))
        self.assertTrue(release.is_excluded("plugins/goal-teams/evals/results/x.json"))
        self.assertFalse(release.is_excluded("plugins/goal-teams/evals/cases.json"))


# -------------------------------------------------------------------- verify


@unittest.skipUnless(HAS_GIT, "git is required")
class VerifyTestCase(ReleaseTestCase):
    """Builds one release per class; every test gets a fresh copy of it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._fixture = tempfile.TemporaryDirectory()
        base = Path(cls._fixture.name).resolve()
        env = environment(base)
        repo = make_repo(env, base / "repo")
        code, stdout, stderr = run_tool(env, "build", "--root", str(repo), "--out", str(base / "dist"))
        if code != 0:
            cls._fixture.cleanup()
            raise RuntimeError(stdout + stderr)
        cls.golden = base / "dist"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fixture.cleanup()

    def fresh(self) -> Path:
        dist = self.tmp / "assets"
        if dist.exists():
            shutil.rmtree(dist)
        shutil.copytree(self.golden, dist)
        return dist

    def assert_refused(self, dist: Path, *expected: str, extra: Tuple[str, ...] = ()) -> str:
        code, output = self.verify(dist, *extra)
        self.assertEqual(code, 1, output)
        self.assertIn("RESULT: FAILED", output)
        for text in expected:
            self.assertIn(text, output)
        return output


class VerifyTests(VerifyTestCase):
    def test_fresh_release_verifies(self) -> None:
        code, output = self.verify(self.fresh())
        self.assertEqual(code, 0, output)
        self.assertIn("RESULT: OK", output)
        self.assertIn("authenticity NOT verified", output)
        self.assertIn("recorded; not checked against git", output)

    def test_changed_tarball_byte_is_detected(self) -> None:
        dist = self.fresh()
        data = bytearray((dist / TARBALL).read_bytes())
        data[len(data) // 2] ^= 0xFF
        (dist / TARBALL).write_bytes(bytes(data))
        self.assert_refused(dist, f"{TARBALL}: SHA-256 does not match SHA256SUMS",
                            f"{TARBALL}: SHA-256 differs from release.json")

    def test_mismatched_sha256sums_is_detected(self) -> None:
        dist = self.fresh()
        lines = (dist / "SHA256SUMS").read_bytes().decode("ascii").splitlines()
        lines[1] = "0" * 64 + lines[1][64:]
        (dist / "SHA256SUMS").write_bytes(("\n".join(lines) + "\n").encode("ascii"))
        self.assert_refused(dist, "release.json: SHA-256 does not match SHA256SUMS")

    def test_unexpected_and_missing_assets_are_detected(self) -> None:
        dist = self.fresh()
        (dist / ".DS_Store").write_bytes(b"\0")  # OS metadata in a download folder is ignored
        code, output = self.verify(dist)
        self.assertEqual(code, 0, output)
        (dist / "notes.txt").write_bytes(b"x")
        self.assert_refused(dist, "notes.txt: unexpected file, not covered by SHA256SUMS")
        dist = self.fresh()
        (dist / "release.json").unlink()
        self.assert_refused(dist, "release.json: listed in SHA256SUMS but missing")
        dist = self.fresh()
        (dist / "SHA256SUMS").unlink()
        self.assert_refused(dist, "SHA256SUMS is missing")

    def test_asset_set_id_binds_the_listed_files_and_tarball(self) -> None:  # AC26/AC27
        dist = self.fresh()
        manifest = json.loads((dist / "release.json").read_bytes())
        manifest["files"] = manifest["files"][:-1]  # a file list rewritten without re-issuing the set id
        data = (json.dumps(manifest, indent=2) + "\n").encode("ascii")
        (dist / "release.json").write_bytes(data)
        tarball = (dist / TARBALL).read_bytes()
        (dist / "SHA256SUMS").write_bytes(f"{sha(tarball)}  {TARBALL}\n{sha(data)}  release.json\n".encode("ascii"))
        self.assert_refused(dist, "release.json: asset_set_id does not match the listed files and tarball")

    def test_extra_member_is_detected(self) -> None:
        dist = self.fresh()
        retar(dist, lambda m: m + [new_member(f"{TOP}/plugins/goal-teams/extra.md", data=b"extra\n")])
        self.assert_refused(dist, "plugins/goal-teams/extra.md: in the tarball but not listed in release.json")

    def test_missing_and_modified_members_are_detected(self) -> None:
        dist = self.fresh()
        retar(dist, lambda m: [item for item in m if item[0].name != f"{TOP}/{SKILL}"])
        self.assert_refused(dist, f"{SKILL}: listed in release.json but not in the tarball")

        def modify(members: List[Member]) -> List[Member]:
            result = []
            for info, data in members:
                if info.name == f"{TOP}/{SKILL}":
                    data = b"# replaced\n"
                    info.size = len(data)
                result.append((info, data))
            return result

        dist = self.fresh()
        retar(dist, modify)
        self.assert_refused(dist, f"{SKILL}: size or SHA-256 differs from release.json")

    def test_dotdot_absolute_and_outside_members_are_refused(self) -> None:
        cases = (
            (f"{TOP}/../evil", "'..' path component"),
            ("../evil", "'..' path component"),
            (f"{TOP}/plugins/../../evil", "'..' path component"),
            ("/etc/evil", "absolute path"),
            ("other/file.txt", "outside the top directory"),
            (f"{TOP}/C:evil", "colon"),
            (f"{TOP}/a\\b", "backslash"),
        )
        for name, message in cases:
            with self.subTest(name=name):
                dist = self.fresh()
                retar(dist, lambda m: m + [new_member(name, data=b"x")])
                self.assert_refused(dist, f"member {name!r}", message)

    def test_links_devices_and_special_modes_are_refused(self) -> None:
        cases = (
            (tarfile.SYMTYPE, "symlink entries are not allowed"),
            (tarfile.LNKTYPE, "hard link entries are not allowed"),
            (tarfile.CHRTYPE, "device entries are not allowed"),
            (tarfile.BLKTYPE, "device entries are not allowed"),
            (tarfile.FIFOTYPE, "fifo entries are not allowed"),
        )
        for kind, message in cases:
            with self.subTest(message=message, kind=kind):
                dist = self.fresh()
                link = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                retar(dist, lambda m: m + [new_member(f"{TOP}/plugins/goal-teams/node", kind, linkname=link)])
                self.assert_refused(dist, message)

        def setuid(members: List[Member]) -> List[Member]:
            for info, _ in members:
                if info.name == f"{TOP}/{GT}":
                    info.mode = 0o4755
            return members

        dist = self.fresh()
        retar(dist, setuid)
        self.assert_refused(dist, "mode 4755, expected 644 or 755")

    def test_duplicate_member_is_refused(self) -> None:
        dist = self.fresh()
        retar(dist, lambda m: m + [item for item in m if item[0].name == f"{TOP}/{SKILL}"])
        self.assert_refused(dist, f"member '{TOP}/{SKILL}': duplicate")

    def test_tree_structure_rules_hold_even_when_listed(self) -> None:
        cases = (
            ("no directory entry", [new_member(f"{TOP}/newdir/x.md", data=b"x\n")],
             "its directory entry is missing or comes later"),
            ("file used as a directory", [new_member(f"{TOP}/LICENSE/x.md", data=b"x\n")],
             "its directory entry is missing or comes later"),
            ("case collision", [new_member(f"{TOP}/license", data=b"x\n")], "differs only by case"),
            ("empty directory", [new_member(f"{TOP}/empty", tarfile.DIRTYPE, mode=0o755)],
             "not implied by any file"),
        )
        for label, added, message in cases:
            with self.subTest(label):
                dist = self.fresh()
                manifest = json.loads((dist / "release.json").read_bytes())
                files = sorted(
                    manifest["files"]
                    + [{"path": info.name[len(TOP) + 1:], "size": len(data), "sha256": sha(data)}
                       for info, data in added if data is not None],
                    key=lambda item: item["path"],
                )
                retar(dist, lambda m: m + added, files)
                self.assert_refused(dist, message)

    def test_unexpected_pax_records_are_refused(self) -> None:
        def with_xattr(members: List[Member]) -> List[Member]:
            for info, _ in members:
                if info.name == f"{TOP}/{SKILL}":
                    info.pax_headers = {"SCHILY.xattr.user.evil": "1"}
            return members

        dist = self.fresh()
        retar(dist, with_xattr)
        self.assert_refused(dist, "unexpected PAX records ['SCHILY.xattr.user.evil']")
        dist = self.fresh()
        members = read_members(dist / TARBALL)
        (dist / TARBALL).write_bytes(gzip.compress(tar_stream(members, {"comment": "hi"}), mtime=0))
        reseal(dist)
        self.assert_refused(dist, "global PAX headers are not allowed")

    def test_data_after_the_end_of_archive_is_refused(self) -> None:
        dist = self.fresh()
        stream = gzip.decompress((dist / TARBALL).read_bytes())
        hidden = tar_stream([new_member(f"{TOP}/hidden.md", data=b"hidden\n")])
        (dist / TARBALL).write_bytes(gzip.compress(stream + hidden, mtime=0))
        reseal(dist)
        self.assert_refused(dist, "data after the end-of-archive marker")


class SignatureTests(VerifyTestCase):
    def sign(self, dist: Path, seed: bytes = SEED) -> Path:
        public, signature = ed25519_sign(seed, (dist / "SHA256SUMS").read_bytes())
        (dist / "SHA256SUMS.sig").write_bytes(signature)
        key = self.tmp / f"key-{seed[0]}.pub"
        key.write_bytes(pem(public))
        return key

    def test_test_signer_reproduces_rfc8032_vectors(self) -> None:
        for seed, public, message, signature in RFC8032:
            with self.subTest(public=public):
                self.assertEqual(
                    ed25519_sign(bytes.fromhex(seed), bytes.fromhex(message)),
                    (bytes.fromhex(public), bytes.fromhex(signature)),
                )

    def test_signed_release_verifies_with_pubkey(self) -> None:
        dist = self.fresh()
        key = self.sign(dist)
        code, output = self.verify(dist, "--pubkey", str(key))
        self.assertEqual(code, 0, output)
        self.assertIn("signature    ok (Ed25519", output)

    def test_default_key_comes_from_the_repository(self) -> None:
        dist = self.fresh()
        public, signature = ed25519_sign(SEED, (dist / "SHA256SUMS").read_bytes())
        (dist / "SHA256SUMS.sig").write_bytes(signature)
        checkout = self.tmp / "checkout"
        (checkout / "keys").mkdir(parents=True)
        (checkout / "keys" / "release-ed25519.pub").write_bytes(public.hex().encode("ascii") + b"\n")
        code, stdout, stderr = self.run_tool("verify", str(dist), "--root", str(checkout))
        self.assertEqual(code, 0, stdout + stderr)
        self.assertIn("release-ed25519.pub", stdout)

    def test_signature_without_a_key_fails(self) -> None:
        dist = self.fresh()
        self.sign(dist)
        self.assert_refused(dist, "SHA256SUMS.sig is present but no public key is available")

    def test_pubkey_without_a_signature_fails(self) -> None:
        dist = self.fresh()
        key = self.sign(dist)
        (dist / "SHA256SUMS.sig").unlink()
        self.assert_refused(dist, "SHA256SUMS.sig is missing", extra=("--pubkey", str(key)))

    def test_signature_by_another_key_or_truncated_fails(self) -> None:
        dist = self.fresh()
        key = self.sign(dist)
        self.sign(dist, OTHER_SEED)
        self.assert_refused(dist, "not a valid Ed25519 signature", extra=("--pubkey", str(key)))
        signature = (dist / "SHA256SUMS.sig").read_bytes()
        (dist / "SHA256SUMS.sig").write_bytes(signature[:63])
        self.assert_refused(dist, "raw 64-byte Ed25519 signature (got 63 bytes)", extra=("--pubkey", str(key)))

    def test_consistent_forgery_is_caught_only_by_the_signature(self) -> None:
        dist = self.fresh()
        key = self.sign(dist)
        manifest = json.loads((dist / "release.json").read_bytes())
        payload = b"print('evil')\n"
        files = sorted(
            manifest["files"] + [{"path": "plugins/goal-teams/evil.py", "size": len(payload), "sha256": sha(payload)}],
            key=lambda item: item["path"],
        )
        retar(dist, lambda m: m + [new_member(f"{TOP}/plugins/goal-teams/evil.py", data=payload)], files)
        output = self.assert_refused(dist, "not a valid Ed25519 signature", extra=("--pubkey", str(key)))
        self.assertIn("RESULT: FAILED (1 problem)", output)
        (dist / "SHA256SUMS.sig").unlink()
        code, output = self.verify(dist)  # unsigned: internally consistent, so integrity checks pass
        self.assertEqual(code, 0, output)
        self.assertIn("authenticity NOT verified", output)

    @unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
    def test_openssl_signature_round_trip(self) -> None:
        dist = self.fresh()
        private, public = self.tmp / "key.pem", self.tmp / "pub.pem"
        for command in (
            ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
            ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private),
             "-in", str(dist / "SHA256SUMS"), "-out", str(dist / "SHA256SUMS.sig")],
        ):
            proc = subprocess.run(command, stdout=PIPE, stderr=PIPE)
            if proc.returncode != 0:
                self.skipTest("this openssl cannot make raw Ed25519 signatures")
        if (dist / "SHA256SUMS.sig").stat().st_size != 64:
            self.skipTest("this openssl does not write raw 64-byte Ed25519 signatures")
        code, output = self.verify(dist, "--pubkey", str(public))
        self.assertEqual(code, 0, output)


# ---------------------------------------------------------- notes, check-tag


class NotesAndTagTests(ReleaseTestCase):
    def test_section_for_the_exact_version(self) -> None:
        body = release.changelog_section(CHANGELOG, "3.0.0")
        self.assertTrue(body.startswith("### 新增\n"), body)
        self.assertIn("## not a heading inside a fence", body)
        self.assertTrue(body.endswith("```\n"), body)
        self.assertNotIn("short form", body)
        self.assertEqual(release.changelog_section(CHANGELOG, "2.68"), "- old\n")

    def test_short_heading_and_version_boundaries(self) -> None:
        text = (
            "# Changelog\n\n## V13.0.0\n\n- thirteen\n\n## V3.0.1\n\n- patch\n\n"
            "## V3.0 — 2026-10-01\n\n- short\n\n## 3.0.0-rc.1\n\n- rc\n\n# Appendix\n\n- end\n"
        )
        self.assertEqual(release.changelog_section(text, "3.0.0"), "- short\n")
        self.assertEqual(release.changelog_section(text, "3.0.1"), "- patch\n")
        self.assertEqual(release.changelog_section(text, "3.0.0-rc.1"), "- rc\n")
        self.assertIsNone(release.changelog_section(text, "4.0.0"))

    def test_notes_command(self) -> None:
        root = self.tmp / "checkout"
        root.mkdir()
        (root / "CHANGELOG.md").write_bytes(CHANGELOG.encode("utf-8"))
        proc = subprocess.run(
            [sys.executable, str(TOOL), "notes", "3.0.0", "--root", str(root)],
            env=self.env, stdout=PIPE, stderr=PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.decode("utf-8"), release.changelog_section(CHANGELOG, "3.0.0"))
        code, _, stderr = self.run_tool("notes", "9.9.9", "--root", str(root))
        self.assertEqual(code, 1)
        self.assertIn("no '## ' heading for version 9.9.9", stderr)

    def test_check_tag(self) -> None:
        root = self.tmp / "checkout"
        root.mkdir()
        (root / "VERSION").write_bytes(b"3.0.0\n")
        code, stdout, _ = self.run_tool("check-tag", "v3.0.0", "--root", str(root))
        self.assertEqual(code, 0)
        self.assertIn("matches VERSION 3.0.0", stdout)
        for tag in ("3.0.0", "v3.0", "V3.0.0", "v3.0.0 ", "v3.0.1", "refs/tags/v3.0.0"):
            with self.subTest(tag=tag):
                self.assertEqual(self.run_tool("check-tag", tag, "--root", str(root))[0], 1)
        (root / "VERSION").write_bytes(b"V2.68\n")
        code, _, stderr = self.run_tool("check-tag", "vV2.68", "--root", str(root))
        self.assertEqual(code, 1)
        self.assertIn("must look like 2.7.0", stderr)


if __name__ == "__main__":
    unittest.main()
