"""Tests for tools/install.py (stdlib unittest; temporary directories only, never the real home).

Run from the repo root:  python3 -m unittest tests.test_install -v
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_PY = os.path.join(ROOT, "tools", "install.py")
_spec = importlib.util.spec_from_file_location("goal_teams_install", INSTALL_PY)
install = importlib.util.module_from_spec(_spec)
_write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # keep tools/ free of __pycache__
_spec.loader.exec_module(install)
sys.dont_write_bytecode = _write_bytecode
GIT = shutil.which("git")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def snapshot(root):
    """{relative path: sha256 | 'dir' | 'link:<target>'} of everything below root, or None if missing."""
    if not os.path.lexists(root):
        return None
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                snap[rel] = "link:" + os.readlink(path)
            elif os.path.isdir(path):
                snap[rel] = "dir"
            else:
                with open(path, "rb") as f:
                    snap[rel] = hashlib.sha256(f.read()).hexdigest()
    return snap


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def dead_pid():
    """The pid of a process that has ended (as the installer sees it; a reused pid skips the test)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    if install.alive(proc.pid) is not False:
        raise unittest.SkipTest(f"pid {proc.pid} was reused or cannot be checked")
    return proc.pid


def make_source(root, marker="v1", agents=("goal_backend", "goal_reviewer")):
    """A fake source tree (repo or release layout) with a nested script and agents for both hosts."""
    pkg = os.path.join(root, "plugins", "goal-teams")
    skill = os.path.join(pkg, "skills", "goal-teams")
    write(os.path.join(root, "VERSION"), "3.0.0\n")
    write(os.path.join(skill, "SKILL.md"), f"# Goal Teams {marker}\n")
    write(os.path.join(skill, "rules", "core.md"), "core rules\n")
    write(os.path.join(skill, "scripts", "gt.py"), "print('gt')\n")
    write(os.path.join(skill, "scripts", "gt", "nested", "deep.py"), f"VALUE = {marker!r}\n")
    write(os.path.join(skill, "scripts", "gt", "__pycache__", "deep.cpython-39.pyc"), "junk")
    write(os.path.join(skill, ".DS_Store"), "junk")
    write(os.path.join(skill, "evals", "results", "run.json"), "{}")
    for agent_dir in (os.path.join(pkg, "codex", "agents"), os.path.join(pkg, "agents")):
        if os.path.isdir(agent_dir):
            shutil.rmtree(agent_dir)
    for name in agents:
        write(os.path.join(pkg, "codex", "agents", name + ".toml"), f'name = "{name}"\n# {marker}\n')
        write(os.path.join(pkg, "agents", name + ".md"), f"---\nname: {name}\n---\n{marker}\n")
    return root


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gt-install-test-")
        self.addCleanup(install.remove, self.tmp)
        self.user_home = os.path.join(self.tmp, "user")  # a fake ~ so that defaults can never reach the real one
        os.makedirs(self.user_home)
        fake = {"HOME": self.user_home, "USERPROFILE": self.user_home,
                "XDG_CONFIG_HOME": os.path.join(self.user_home, ".config")}  # git: no real global config
        env = mock.patch.dict(os.environ, fake)
        env.start()
        self.addCleanup(env.stop)
        for var in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "GOAL_TEAMS_INSTALL_FAIL_AT"):
            os.environ.pop(var, None)
        stdin = mock.patch.object(sys, "stdin", io.StringIO(""))  # not a terminal: never prompt
        stdin.start()
        self.addCleanup(stdin.stop)
        self.src = make_source(os.path.join(self.tmp, "src"))
        self.home = os.path.join(self.tmp, "home")  # the host home: --home in-process, $CODEX_HOME in subprocesses
        self.skill = os.path.join(self.user_home, ".agents", "skills", "goal-teams")  # where Codex gets the skill
        self.legacy = os.path.join(self.home, "skills", "goal-teams")  # the old Codex location
        self.agents = os.path.join(self.home, "agents")
        self.backup_root = os.path.join(self.home, "goal-teams-backups")

    def sub_env(self, **extra):
        """Environment of a subprocess: every home variable points into the throwaway directory."""
        env = dict(os.environ, HOME=self.user_home, USERPROFILE=self.user_home,
                   XDG_CONFIG_HOME=os.path.join(self.user_home, ".config"),
                   CODEX_HOME=self.home, CLAUDE_CONFIG_DIR=os.path.join(self.tmp, "claude-home"))
        env.pop("GOAL_TEAMS_INSTALL_FAIL_AT", None)
        env.update(extra)
        return env

    def run_script(self, *args, script=INSTALL_PY):
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=self.sub_env())

    def git(self, cwd, *args):
        return subprocess.run([GIT, "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@example.com",
                               "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True,
                              env=self.sub_env()).stdout

    def make_clone(self, path):
        """A git clone, as older versions were installed, with a commit and an uncommitted edit."""
        os.makedirs(path)
        self.git(path, "init", "-q")
        write(os.path.join(path, "SKILL.md"), "v2 clone\n")
        self.git(path, "add", "SKILL.md")
        self.git(path, "commit", "-qm", "v2 commit")
        write(os.path.join(path, "SKILL.md"), "v2 clone + local edit\n")  # uncommitted work

    def run_cli(self, *args, home=None, host="codex", source=None):
        argv = list(args) + ["--home", home or self.home, "--source", source or self.src]
        argv += ["--host", host] if host else []
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = install.main(argv)
        return code, out.getvalue()

    def run_json(self, *args, **kwargs):
        code, text = self.run_cli("--json", *args, **kwargs)
        data = json.loads(text)
        self.assertEqual(data["exit"], code)
        return data

    def ok(self, *args, **kwargs):
        code, text = self.run_cli(*args, **kwargs)
        self.assertEqual(code, 0, text)
        return text

    def manifest(self, skill=None):
        return json.loads(read(os.path.join(skill or self.skill, ".goal-teams-install.json")))

    def backups(self):
        return sorted(os.listdir(self.backup_root)) if os.path.isdir(self.backup_root) else []

    def backup_meta(self, backup_id):
        return json.loads(read(os.path.join(self.backup_root, backup_id, "backup.json")))

    # -------------------------------------------------------------- install + verify
    def test_install_codex_writes_manifest_and_verifies_clean(self):
        text = self.ok()
        self.assertIn(f"installed Goal Teams 3.0.0 for codex: 4 files -> {self.skill}, 2 agents -> {self.agents}", text)
        m = self.manifest()
        self.assertEqual((m["schema"], m["version"], m["host"]), ("goal-teams/install@1", "3.0.0", "codex"))
        self.assertEqual(m["source"], {"path": os.path.abspath(self.src), "commit": None, "dirty": None})
        self.assertEqual([f["path"] for f in m["files"]],
                         ["SKILL.md", "rules/core.md", "scripts/gt.py", "scripts/gt/nested/deep.py"])
        for entry in m["files"]:
            digest, size = install.sha256_file(os.path.join(self.skill, *entry["path"].split("/")))
            self.assertEqual((entry["sha256"], entry["size"]), (digest, size))
        self.assertEqual([a["path"] for a in m["agents"]], ["agents/goal_backend.toml", "agents/goal_reviewer.toml"])
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml"])
        for skipped in ("scripts/gt/__pycache__", ".DS_Store", "evals"):
            self.assertFalse(os.path.lexists(os.path.join(self.skill, skipped)), skipped)
        self.assertFalse(os.path.lexists(os.path.join(self.home, "skills")), "nothing goes to the old location")
        self.assertEqual(self.backups(), [], "a fresh install has nothing to back up")
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_fresh_codex_install_uses_home_for_the_skill_and_codex_home_for_agents(self):
        res = self.run_script("--host", "codex", "--source", self.src, "--json")  # no --home: the environment decides
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        host = json.loads(res.stdout)["hosts"][0]
        self.assertEqual((host["home"], host["skill"], host["agents"], host["legacy"]),
                         (self.home, self.skill, self.agents, self.legacy))
        self.assertEqual(json.loads(read(os.path.join(self.skill, ".goal-teams-install.json")))["host"], "codex")
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams v1\n")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml"])
        self.assertEqual(sorted(os.listdir(self.home)), ["agents"], "no skills folder, no lock left in CODEX_HOME")
        self.assertEqual(sorted(os.listdir(self.user_home)), [".agents"])
        res = self.run_script("--verify")  # default host: codex, because $CODEX_HOME is set
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("auto: $CODEX_HOME", res.stdout)
        self.assertIn(f"at {self.skill}", res.stdout)
        self.assertIn("verify: OK", res.stdout)

    def test_install_claude_uses_md_agents_and_prints_plugin_hint(self):
        text = self.ok(host="claude")
        self.assertIn("/plugin install goal-teams@", text)
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.md", "goal_reviewer.md"])
        self.assertEqual(self.manifest(os.path.join(self.home, "skills", "goal-teams"))["host"], "claude")
        self.assertFalse(os.path.lexists(os.path.join(self.user_home, ".agents")), "Claude Code skills stay in its home")
        self.ok("--verify", host="claude")

    def test_skills_dir_overrides_the_skills_folder(self):
        skills = os.path.join(self.tmp, "repo", ".agents", "skills")
        skill = os.path.join(skills, "goal-teams")
        text = self.ok("--skills-dir", skills)
        self.assertIn(f"--verify --host codex --home {install.q(self.home)} --skills-dir {install.q(skills)}", text)
        self.assertEqual(self.manifest(skill)["host"], "codex")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml"])
        self.assertFalse(os.path.lexists(os.path.join(self.user_home, ".agents")))
        self.assertIn("verify: OK", self.ok("--verify", "--skills-dir", skills))
        self.assertEqual(self.run_cli("--verify")[0], 2, "nothing in the default skills folder")
        self.ok("--uninstall", "--skills-dir", skills)
        self.assertFalse(os.path.lexists(skill))
        self.ok("--rollback", "--skills-dir", skills)
        self.ok("--verify", "--skills-dir", skills)
        claude_skills = os.path.join(self.tmp, "claude-skills")
        self.ok("--skills-dir", claude_skills, host="claude", home=os.path.join(self.tmp, "claude-home"))
        self.assertEqual(self.manifest(os.path.join(claude_skills, "goal-teams"))["host"], "claude")

    def test_skills_dir_overlapping_the_host_home_or_both_hosts_is_refused(self):
        before = snapshot(self.tmp)
        for bad in (self.legacy, self.agents, self.backup_root):
            code, text = self.run_cli("--skills-dir", bad)
            self.assertEqual(code, 2, text)
            self.assertIn("overlap", text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = install.main(["--host", "both", "--skills-dir", os.path.join(self.tmp, "s"), "--source", self.src])
        self.assertEqual(code, 2, out.getvalue())
        self.assertIn("--skills-dir", out.getvalue())
        self.assertEqual(self.run_cli(host="both")[0], 2, "--home applies to one host")
        self.assertEqual(snapshot(self.tmp), before)

    def test_verify_reports_modified_missing_and_extra(self):
        self.ok()
        write(os.path.join(self.skill, "scripts", "gt", "__pycache__", "gt.cpython-39.pyc"), "cache")
        self.ok("--verify")  # caches written by running gt are not drift
        write(os.path.join(self.skill, "rules", "core.md"), "edited\n")
        os.remove(os.path.join(self.skill, "scripts", "gt.py"))
        write(os.path.join(self.skill, "notes.txt"), "mine\n")
        write(os.path.join(self.agents, "goal_backend.toml"), "edited\n")
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 1, text)
        for line in ("modified: rules/core.md", "missing: scripts/gt.py", "extra: notes.txt",
                     "modified: agents/goal_backend.toml", "verify: DRIFT"):
            self.assertIn(line, text)
        data = self.run_json("--verify")
        self.assertEqual((data["hosts"][0]["extra"], data["hosts"][0]["duplicate"]), (["notes.txt"], []))

    def test_verify_reports_a_second_copy_at_the_old_location(self):
        self.ok()
        write(os.path.join(self.legacy, "SKILL.md"), "V2\n")
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 1, text)
        self.assertIn(f"duplicate: {self.legacy}", text)
        self.assertEqual(self.run_json("--verify")["hosts"][0]["duplicate"], [self.legacy])
        self.ok()  # installing again moves it into a backup
        self.assertFalse(os.path.lexists(self.legacy))
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_verify_without_install_is_refused(self):
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 2, text)

    # -------------------------------------------------------------- backups
    def test_reinstall_creates_backup_of_previous_install(self):
        self.ok()
        text = self.ok()
        (bid,) = self.backups()
        self.assertIn(os.path.join(self.backup_root, bid), text)
        meta = self.backup_meta(bid)
        self.assertEqual((meta["status"], meta["reason"], meta["protected"]), ("complete", "install", False))
        self.assertEqual(sorted(i["to"] for i in meta["items"]),
                         ["agents/goal_backend.toml", "agents/goal_reviewer.toml", "skill"])
        self.assertTrue(os.path.isfile(os.path.join(self.backup_root, bid, "skill", ".goal-teams-install.json")))
        self.ok("--verify")

    def test_keeps_only_newest_three_backups(self):
        self.ok()
        made = [self.run_json()["hosts"][0]["backup"] for _ in range(5)]
        self.assertEqual(self.backups(), sorted(os.path.basename(p) for p in made[-3:]))
        listed = self.run_json("--list-backups")["hosts"][0]["backups"]
        self.assertEqual([b["path"] for b in listed], made[::-1][:3], "newest first")

    def test_backup_holding_your_own_changes_is_never_pruned_and_rollback_restores_them(self):
        self.ok()
        mine = {os.path.join(self.skill, "rules", "core.md"): b"my rules\r\n\x00\xff",  # edited, odd bytes
                os.path.join(self.skill, "notes", "mine.md"): b"my notes\n",  # added
                os.path.join(self.agents, "goal_backend.toml"): b'name = "goal_backend"\n# tuned by me\n'}
        for path, data in mine.items():
            write_bytes(path, data)
        edited = snapshot(self.skill)
        text = self.ok()  # an update moves the whole edited install into a backup
        (bid,) = self.backups()
        self.assertIn("backup contains your own changes: 2 modified: skill/rules/core.md, agents/goal_backend.toml; "
                      "1 extra: skill/notes/mine.md; it is kept until you delete it", text)
        meta = self.backup_meta(bid)
        self.assertTrue(meta["protected"])
        self.assertEqual(meta["drift"], {"modified": ["skill/rules/core.md", "agents/goal_backend.toml"],
                                         "missing": [], "extra": ["skill/notes/mine.md"]})
        self.assertEqual(self.run_json("--list-backups")["hosts"][0]["backups"][0]["drift"], meta["drift"])
        self.assertIn(f"{bid}  install   complete    previous: Goal Teams 3.0.0 (managed install)"
                      "  [never pruned: holds your own changes]", self.ok("--list-backups"))
        self.assertIn("verify: OK", self.ok("--verify"))  # the live install is clean again
        for _ in range(4):
            text = self.ok()  # clean updates; their backups are the ones that get pruned
        self.assertIn("pruned 1 old backup(s); the newest 3 clean backups are kept", text)
        self.assertIn(bid, self.backups(), "the backup with the edits is never pruned")
        self.assertEqual(len(self.backups()), 4)  # it + the newest 3 clean ones
        self.ok("--rollback", bid)
        self.assertEqual(snapshot(self.skill), edited, "restored byte for byte, manifest included")
        for path, data in mine.items():
            self.assertEqual(read_bytes(path), data, path)
        code, text = self.run_cli("--verify")  # the edits are back, so the manifest check reports them again
        self.assertEqual(code, 1, text)
        for line in ("modified: rules/core.md", "extra: notes/mine.md", "modified: agents/goal_backend.toml"):
            self.assertIn(line, text)
        self.assertEqual(len(self.backups()), 5, "the rollback backs up the clean install it replaced")
        self.assertFalse(self.backup_meta(self.backups()[-1])["protected"])

    def test_uninstall_backup_holding_edited_files_is_protected(self):
        self.ok()
        write(os.path.join(self.skill, "rules", "core.md"), "edited\n")
        os.remove(os.path.join(self.skill, "scripts", "gt.py"))
        write(os.path.join(self.skill, "notes.txt"), "mine\n")
        text = self.ok("--uninstall")
        self.assertIn("backup contains your own changes: 1 modified: skill/rules/core.md; "
                      "1 missing: skill/scripts/gt.py; it is kept until you delete it", text)
        (bid,) = self.backups()
        meta = self.backup_meta(bid)
        self.assertTrue(meta["protected"])
        self.assertEqual(meta["drift"], {"modified": ["skill/rules/core.md"], "missing": ["skill/scripts/gt.py"],
                                         "extra": []}, "files not in the manifest stay in place, so they do not count")
        self.assertEqual(read(os.path.join(self.backup_root, bid, "skill", "rules", "core.md")), "edited\n")
        self.assertEqual(snapshot(self.skill), {"notes.txt": snapshot(self.skill)["notes.txt"]})
        self.ok("--rollback", bid)
        self.assertEqual(read(os.path.join(self.skill, "rules", "core.md")), "edited\n")
        self.assertFalse(os.path.lexists(os.path.join(self.skill, "scripts", "gt.py")))
        self.assertTrue(self.backup_meta(self.backups()[-1])["protected"], "the leftover dir was unmanaged")

    # -------------------------------------------------------------- uninstall
    def test_uninstall_removes_only_manifest_files(self):
        self.ok()
        write(os.path.join(self.skill, "notes", "mine.md"), "user file\n")
        write(os.path.join(self.skill, "scripts", "gt", "__pycache__", "x.pyc"), "cache")
        write(os.path.join(self.agents, "my_agent.toml"), "user agent\n")
        text = self.ok("--uninstall")
        self.assertIn("kept 1 file(s)", text)
        self.assertEqual(snapshot(self.skill), {"notes": "dir", "notes/mine.md": snapshot(self.skill)["notes/mine.md"]})
        self.assertEqual(os.listdir(self.agents), ["my_agent.toml"])
        (bid,) = self.backups()
        saved = os.path.join(self.backup_root, bid)
        self.assertTrue(os.path.isfile(os.path.join(saved, "skill", "scripts", "gt", "nested", "deep.py")))
        self.assertTrue(os.path.isfile(os.path.join(saved, "agents", "goal_backend.toml")))
        self.assertEqual(self.run_cli("--uninstall")[0], 2, "a leftover unmanaged dir is left alone")

    def test_uninstall_then_rollback_restores_install(self):
        self.ok()
        self.ok("--uninstall")
        self.assertFalse(os.path.exists(self.skill))
        self.ok("--rollback")
        self.ok("--verify")

    def test_uninstall_also_moves_a_managed_install_at_the_old_location(self):
        old_skills = os.path.join(self.home, "skills")
        self.ok()
        self.ok("--skills-dir", old_skills)  # the layout of the previous installer: <codex home>/skills/goal-teams
        text = self.ok("--uninstall")
        self.assertIn(f"(also the old install at {self.legacy})", text)
        self.assertFalse(os.path.lexists(self.skill))
        self.assertFalse(os.path.lexists(self.legacy))
        self.assertTrue(os.path.isdir(old_skills), "the skills folder itself stays")
        self.assertEqual(os.listdir(self.agents), [])
        saved = os.path.join(self.backup_root, self.backups()[-1])
        for folder in ("skill", "legacy-skill"):
            self.assertTrue(os.path.isfile(os.path.join(saved, folder, ".goal-teams-install.json")), folder)
        self.ok("--rollback")  # puts both copies back, as they were
        self.ok("--verify", "--skills-dir", old_skills)
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 1, text)
        self.assertIn("duplicate", text)

    def test_uninstall_leaves_an_unmanaged_old_location_alone(self):
        self.ok()
        write(os.path.join(self.legacy, "SKILL.md"), "V2\n")
        text = self.ok("--uninstall")
        self.assertIn("left alone", text)
        self.assertFalse(os.path.lexists(self.skill))
        self.assertEqual(read(os.path.join(self.legacy, "SKILL.md")), "V2\n")
        text = self.ok("--uninstall")
        self.assertIn("nothing to uninstall", text)
        self.assertIn("left alone", text)

    # -------------------------------------------------------------- the old Codex location
    @unittest.skipUnless(GIT, "git is not installed")
    def test_old_clone_at_old_location_is_kept_in_a_backup_and_restored_by_rollback(self):
        self.make_clone(self.legacy)
        write(os.path.join(self.agents, "goal-backend.toml"), "# V2 agent\n")
        others = {os.path.join(self.home, "skills", ".system", "openai-docs", "SKILL.md"): "codex\n",
                  os.path.join(self.home, "skills", "my-skill", "SKILL.md"): "mine\n"}
        for path, text in others.items():
            write(path, text)
        text = self.ok()
        self.assertIn(f"old location: {self.legacy} (now: a git clone WITH UNCOMMITTED CHANGES)", text)
        self.assertIn("MOVED (not deleted)", text)
        self.assertFalse(os.path.lexists(self.legacy))
        self.assertEqual({p: read(p) for p in others}, others, "the rest of <codex home>/skills is left alone")
        (bid,) = self.backups()
        clone = os.path.join(self.backup_root, bid, "legacy-skill")
        self.assertEqual(read(os.path.join(clone, "SKILL.md")), "v2 clone + local edit\n")
        self.assertEqual(self.git(clone, "log", "--format=%s").strip(), "v2 commit")
        self.assertIn("SKILL.md", self.git(clone, "status", "--porcelain"))
        meta = self.backup_meta(bid)
        self.assertTrue(meta["protected"])
        self.assertIn(("legacy-skill", self.legacy), [(i["what"], i["from"]) for i in meta["items"]])
        self.assertIn("previous: nothing; old location: a git clone", self.ok("--list-backups"))
        self.ok("--verify")
        for _ in range(4):
            self.ok()
        self.assertIn(bid, self.backups(), "a backup holding a git clone is never pruned")
        self.assertEqual(len(self.backups()), 4)  # the clone + the newest 3
        self.ok("--rollback", bid)
        self.assertEqual(read(os.path.join(self.legacy, "SKILL.md")), "v2 clone + local edit\n")
        self.assertEqual(self.git(self.legacy, "log", "--format=%s").strip(), "v2 commit")
        self.assertIn("SKILL.md", self.git(self.legacy, "status", "--porcelain"))
        self.assertFalse(os.path.lexists(self.skill), "the managed install went into a backup: no second copy")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal-backend.toml"])
        self.ok("--rollback")  # the newest backup: the managed install from before that rollback
        self.assertFalse(os.path.lexists(self.legacy))
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_old_package_at_old_location_and_hyphen_agents_are_moved(self):
        write(os.path.join(self.legacy, "SKILL.md"), "old package\n")
        write(os.path.join(self.legacy, "scripts", "install", "install-local.sh"), "#!/bin/bash\n")
        for name in ("goal-backend.toml", "goal-qa.toml", "team-researcher.toml"):
            write(os.path.join(self.agents, name), f"# {name}\n")
        state = os.path.join(self.home, "state", "goal-teams", "current.json")
        write(state, "{}")
        leftover = os.path.join(self.home, "skills", f".goal-teams-staging-{dead_pid()}")  # an interrupted run
        write(os.path.join(leftover, "SKILL.md"), "partial\n")
        text = self.ok()
        self.assertIn("agent of an older version", text)
        self.assertIn(f"removed leftover staging copy {leftover}", text)
        self.assertIn(os.path.join(self.home, "state", "goal-teams"), text)
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml",
                                                           "team-researcher.toml"])
        self.assertTrue(os.path.isfile(state), "the state of older versions is left alone")
        self.assertEqual(os.listdir(os.path.join(self.home, "skills")), [])
        (bid,) = self.backups()
        saved = os.path.join(self.backup_root, bid)
        self.assertEqual(sorted(os.listdir(os.path.join(saved, "agents"))), ["goal-backend.toml", "goal-qa.toml"])
        self.assertEqual(read(os.path.join(saved, "legacy-skill", "SKILL.md")), "old package\n")
        self.assertFalse(os.path.lexists(os.path.join(saved, "skill")))
        meta = self.backup_meta(bid)
        self.assertTrue(meta["protected"])
        self.assertEqual(meta["drift"]["extra"], ["agents/goal-backend.toml", "agents/goal-qa.toml"],
                         "agents this installer did not write count as your own files")
        self.ok("--verify")

    def test_staging_leftovers_are_removed_only_when_their_process_has_ended(self):
        skills = os.path.dirname(self.skill)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])  # another live process
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        gone = os.path.join(skills, f".skill{install.STAGING}{dead_pid()}")
        live = os.path.join(skills, f".skill{install.STAGING}{other.pid}")
        unknown_new = os.path.join(self.agents, f".goal_x.toml{install.STAGING}x")  # no pid in the name
        unknown_old = os.path.join(skills, ".goal-teams-staging-")
        for path in (gone, live, unknown_new):
            write(os.path.join(path, "SKILL.md"), "partial\n")
        write(unknown_old, "partial\n")
        old = time.time() - 11 * 60
        os.utime(unknown_old, (old, old))
        text = self.ok()
        self.assertIn(f"removed leftover staging copy {gone} (process", text)
        self.assertIn(f"removed leftover staging copy {unknown_old} (older than 10 minutes)", text)
        self.assertIn(f"note: {live} belongs to another install still running (pid {other.pid}); left alone", text)
        self.assertIn(f"note: {unknown_new} may belong to another install; left alone", text)
        self.assertEqual(sorted(os.listdir(skills)), sorted([os.path.basename(live), "goal-teams"]))
        self.assertTrue(os.path.isdir(unknown_new))
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_managed_install_at_old_location_is_moved_and_rollback_puts_it_back(self):
        old_skills = os.path.join(self.home, "skills")
        make_source(self.src, marker="old1", agents=("goal_backend", "goal_qa"))
        self.ok("--skills-dir", old_skills)  # same layout and manifest as an install by the previous installer
        make_source(self.src, marker="old2", agents=("goal_backend", "goal_qa"))
        self.ok("--skills-dir", old_skills)  # its backup holds 'skill' from the old location
        (older,) = self.backups()
        self.assertEqual(self.backup_meta(older)["items"][0]["from"], self.legacy)
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 2, text)
        self.assertIn(f"the old Codex location {self.legacy} holds Goal Teams 3.0.0 (managed install)", text)
        make_source(self.src, marker="new")
        text = self.ok()
        self.assertIn(f"old location: {self.legacy} (now: Goal Teams 3.0.0 (managed install))", text)
        self.assertFalse(os.path.lexists(self.legacy))
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams new\n")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml"])
        meta = self.backup_meta(self.backups()[-1])
        self.assertFalse(meta["protected"], "a clean managed install makes an ordinary backup")
        self.assertEqual(meta["drift"], {"modified": [], "missing": [], "extra": []})
        self.assertEqual(sorted(i["to"] for i in meta["items"]),
                         ["agents/goal_backend.toml", "agents/goal_qa.toml", "legacy-skill"])
        self.assertIn("verify: OK", self.ok("--verify"))
        self.ok("--rollback")  # back where it came from
        self.assertEqual(read(os.path.join(self.legacy, "SKILL.md")), "# Goal Teams old2\n")
        self.assertFalse(os.path.lexists(self.skill))
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_qa.toml"])
        self.ok("--verify", "--skills-dir", old_skills)
        self.ok("--rollback", older)  # a backup made at the old location goes back there too
        self.assertEqual(read(os.path.join(self.legacy, "SKILL.md")), "# Goal Teams old1\n")
        self.assertFalse(os.path.lexists(self.skill))
        self.ok("--verify", "--skills-dir", old_skills)

    def test_dry_run_lists_the_move_of_the_old_location(self):
        write(os.path.join(self.legacy, "SKILL.md"), "V2\n")
        before = snapshot(self.tmp)
        text = self.ok("--dry-run")
        self.assertIn(f"old location: {self.legacy} (now: an unmanaged directory (no install manifest", text)
        self.assertIn(f"  move    {self.legacy}\n       -> {self.backup_root}", text)
        self.assertIn("legacy-skill  (an unmanaged directory (no install manifest", text)
        self.assertIn("never pruned automatically", text)
        self.assertIn(f"  install {self.skill}  (4 files from", text)
        self.assertIn("dry run: nothing changed", text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_interactive_prompt_can_cancel_a_legacy_move(self):
        write(os.path.join(self.legacy, "SKILL.md"), "V2\n")
        before = snapshot(self.tmp)
        with mock.patch.object(sys, "stdin", FakeTTY()), mock.patch("builtins.input", return_value="n") as ask:
            code, text = self.run_cli()
        self.assertEqual((code, ask.call_count), (2, 1), text)
        self.assertIn(self.legacy, ask.call_args[0][0])
        self.assertEqual(snapshot(self.tmp), before)
        with mock.patch.object(sys, "stdin", FakeTTY()), mock.patch("builtins.input") as ask:
            self.ok("--yes")
        self.assertEqual(ask.call_count, 0)
        self.assertFalse(os.path.lexists(self.legacy))

    @unittest.skipUnless(GIT, "git is not installed")
    def test_git_clone_at_the_target_is_moved_into_a_kept_backup(self):
        claude_skill = os.path.join(self.home, "skills", "goal-teams")  # the Claude Code target with --home
        self.make_clone(claude_skill)
        text = self.ok(host="claude")
        self.assertIn("WITH UNCOMMITTED CHANGES", text)
        self.assertIn("MOVED (not deleted)", text)
        (bid,) = self.backups()
        clone = os.path.join(self.backup_root, bid, "skill")
        self.assertEqual(read(os.path.join(clone, "SKILL.md")), "v2 clone + local edit\n")
        self.assertEqual(self.git(clone, "log", "--format=%s").strip(), "v2 commit")
        self.assertTrue(self.backup_meta(bid)["protected"])
        self.ok("--verify", host="claude")
        for _ in range(4):
            self.ok(host="claude")
        self.assertIn(bid, self.backups(), "a backup holding a git clone is never pruned")
        self.assertEqual(len(self.backups()), 4)  # the clone + the newest 3

    # -------------------------------------------------------------- guard
    def test_refuses_source_inside_the_old_location_like_an_old_clone(self):
        clone = make_source(self.legacy)  # git clone ... ~/.codex/skills/goal-teams, as older versions told users to do
        os.makedirs(os.path.join(clone, "tools"))
        shutil.copy2(INSTALL_PY, os.path.join(clone, "tools", "install.py"))
        before = snapshot(self.tmp)
        res = self.run_script("--host", "codex", script=os.path.join(clone, "tools", "install.py"))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn(f"the source tree is inside {self.legacy}, the old Codex skills location", res.stderr)
        self.assertIn(f"mv {install.q(clone)} ~/src/goal-teams && python3 ~/src/goal-teams/tools/install.py",
                      res.stderr)
        for args in ([], ["--dry-run"], ["--yes", "--json"]):
            code, text = self.run_cli(*args, source=clone)
            self.assertEqual(code, 2, text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_refuses_old_location_inside_the_source(self):
        home = os.path.join(self.src, "codex-home")
        write(os.path.join(home, "skills", "goal-teams", "SKILL.md"), "V2\n")
        before = snapshot(self.tmp)
        code, text = self.run_cli(home=home)
        self.assertEqual(code, 2, text)
        self.assertIn("the old Codex skills location, is inside the source tree", text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_refuses_old_location_symlinked_to_source(self):
        os.makedirs(os.path.dirname(self.legacy))
        try:
            os.symlink(self.src, self.legacy, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        before = snapshot(self.tmp)
        code, text = self.run_cli()
        self.assertEqual(code, 2, text)
        self.assertIn("remove just the link", text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_refuses_target_equal_to_source(self):
        pkg = os.path.join(self.src, "plugins", "goal-teams")
        before = snapshot(self.tmp)
        for args, kwargs in ((["--skills-dir", os.path.join(pkg, "skills")], {}), ([], {"home": pkg, "host": "claude"})):
            code, text = self.run_cli(*args, **kwargs)
            self.assertEqual(code, 2, text)
            self.assertIn("the target is the source skill directory", text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_refuses_target_symlinked_to_source(self):
        os.makedirs(os.path.dirname(self.skill))
        try:
            os.symlink(self.src, self.skill, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        before = snapshot(self.tmp)
        code, text = self.run_cli()
        self.assertEqual(code, 2, text)
        self.assertIn("symlink", text)
        self.assertEqual(snapshot(self.tmp), before)

    def test_symlink_out_of_source_is_not_followed(self):
        rules = os.path.join(self.src, "plugins", "goal-teams", "skills", "goal-teams", "rules")
        write(os.path.join(self.tmp, "secret.txt"), "secret\n")
        try:
            os.symlink(os.path.join(self.tmp, "secret.txt"), os.path.join(rules, "outside.md"))
            os.symlink(os.path.join(rules, "core.md"), os.path.join(rules, "inside.md"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        text = self.ok()
        self.assertIn("outside.md: it resolves outside the package", text)
        self.assertFalse(os.path.lexists(os.path.join(self.skill, "rules", "outside.md")))
        inside = os.path.join(self.skill, "rules", "inside.md")
        self.assertFalse(os.path.islink(inside))
        self.assertEqual(read(inside), "core rules\n")

    def test_source_skill_dir_linked_outside_the_source_is_refused(self):
        skill = os.path.join(self.src, "plugins", "goal-teams", "skills", "goal-teams")
        elsewhere = os.path.join(self.tmp, "elsewhere")
        shutil.move(skill, elsewhere)
        try:
            os.symlink(elsewhere, skill, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        code, text = self.run_cli()
        self.assertEqual(code, 2, text)
        self.assertIn("resolves outside", text)
        self.assertIsNone(snapshot(self.home))
        self.assertEqual(os.listdir(self.user_home), [])

    # -------------------------------------------------------------- dry run
    def test_dry_run_changes_nothing(self):
        code, text = self.run_cli("--dry-run")
        self.assertEqual(code, 0, text)
        self.assertIn("dry run: nothing changed", text)
        self.assertIsNone(snapshot(self.home), "a dry run does not even create the home")
        self.assertEqual(os.listdir(self.user_home), [], "nor the skills folder")
        for _ in range(4):
            self.ok()
        before = snapshot(self.tmp)
        self.assertIn("  prune   old backup", self.ok("--dry-run"), "three clean backups: a clean update prunes one")
        self.assertEqual(snapshot(self.tmp), before)
        write(os.path.join(self.agents, "goal-backend.toml"), "legacy\n")
        write(os.path.join(self.skill, "rules", "core.md"), "edited\n")
        before = snapshot(self.tmp)
        text = self.ok("--dry-run")
        self.assertIn("goal-backend.toml", text)
        self.assertIn("note: the backup will contain your own changes (1 modified: skill/rules/core.md; "
                      "1 extra: agents/goal-backend.toml);\n      it is kept until you delete it", text)
        self.assertNotIn("  prune   ", text, "a protected backup does not count against the newest 3")
        self.ok("--uninstall", "--dry-run")
        self.ok("--rollback", "--dry-run")
        self.assertEqual(snapshot(self.tmp), before)

    # -------------------------------------------------------------- rollback
    def test_rollback_restores_previous_version(self):
        self.ok()
        make_source(self.src, marker="v2", agents=("goal_backend", "goal_qa"))
        self.ok()
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams v2\n")
        first = self.backups()[0]
        data = self.run_json("--rollback")
        self.assertEqual(data["exit"], 0)
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams v1\n")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_reviewer.toml"])
        self.assertIn("# v1", read(os.path.join(self.agents, "goal_backend.toml")))
        self.ok("--verify")
        self.ok("--rollback")  # the newest backup is now the state before the rollback: v2 again
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams v2\n")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_qa.toml"])
        self.ok("--rollback", first)
        self.assertEqual(read(os.path.join(self.skill, "SKILL.md")), "# Goal Teams v1\n")
        self.ok("--verify")
        self.assertEqual(self.run_cli("--rollback", "20000101T000000Z-codex")[0], 2)

    # -------------------------------------------------------------- failure handling
    def test_failure_during_switch_restores_old_install(self):
        self.ok()
        write(os.path.join(self.legacy, "SKILL.md"), "V2\n")  # the switch also has to move the old location
        make_source(self.src, marker="v2", agents=("goal_backend", "goal_qa"))
        before = snapshot(self.tmp)
        for point in ("after_skill", "after_switch"):
            with mock.patch.dict(os.environ, {"GOAL_TEAMS_INSTALL_FAIL_AT": point}):
                code, text = self.run_cli()
            self.assertEqual(code, 1, text)
            self.assertIn("simulated failure", text)
            self.assertIn("previous state was restored", text)
            self.assertEqual(snapshot(self.tmp), before, point)
        self.ok()
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_hard_crash_mid_switch_is_undone_from_the_journal_on_the_next_run(self):  # AC30
        self.ok()
        make_source(self.src, marker="v2", agents=("goal_backend", "goal_qa"))
        before = snapshot(self.tmp)
        # a power cut right after the new skill folder went live: no rollback code ran
        res = subprocess.run([sys.executable, INSTALL_PY, "--host", "codex", "--source", self.src],
                             capture_output=True, text=True, env=self.sub_env(GOAL_TEAMS_INSTALL_KILL_AT="after_skill"))
        self.assertEqual(res.returncode, 70, res.stdout + res.stderr)
        journal = os.path.join(self.backup_root, "journal.json")
        self.assertTrue(os.path.isfile(journal), "the journal survives the crash")
        self.assertNotEqual(snapshot(self.tmp), before, "the live folders are half switched")
        code, text = self.run_cli("--verify")
        self.assertEqual(code, 2)
        self.assertIn("interrupted", text)
        text = self.ok()  # the next install first undoes the recorded moves, then installs normally
        self.assertIn("recovered from an interrupted install", text)
        self.assertFalse(os.path.exists(journal))
        self.assertIn("verify: OK", self.ok("--verify"))
        self.assertEqual(self.manifest()["version"], "3.0.0")
        self.assertEqual(sorted(os.listdir(self.agents)), ["goal_backend.toml", "goal_qa.toml"])
        # the files that were live before the crash are in the backup the recovered install made
        self.assertEqual(len(self.backups()), 1)

    def test_9_crash_after_a_rename_before_the_journal_update_is_undone(self):
        self.ok()
        make_source(self.src, marker="v2")
        before = snapshot(self.tmp)
        for point in ("after_skill",):
            env = self.sub_env(GOAL_TEAMS_INSTALL_KILL_AT="moved")
            res = subprocess.run([sys.executable, INSTALL_PY, "--host", "codex", "--source", self.src],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 70, res.stdout + res.stderr)
        text = self.ok("--rollback")
        self.assertRegex(text, r"[1-9] move\(s\) undone")
        self.assertEqual(snapshot(self.tmp), before)

    def test_rollback_undoes_an_interrupted_switch_first(self):  # AC30
        self.ok()
        make_source(self.src, marker="v2")
        before = snapshot(self.tmp)
        subprocess.run([sys.executable, INSTALL_PY, "--host", "codex", "--source", self.src],
                       capture_output=True, text=True, env=self.sub_env(GOAL_TEAMS_INSTALL_KILL_AT="after_skill"))
        text = self.ok("--rollback")
        self.assertIn("interrupted install is undone", text)
        self.assertEqual(snapshot(self.tmp), before, "exactly the state before the crashed install")
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_dry_run_creates_nothing(self):  # AC30
        make_source(self.src, marker="v1")
        before = snapshot(self.tmp)
        text = self.ok("--dry-run")
        self.assertIn("dry run: nothing changed", text)
        self.assertEqual(snapshot(self.tmp), before, "no directory, lock, backup or journal is created")

    def test_failure_on_fresh_install_leaves_nothing_behind(self):
        with mock.patch.dict(os.environ, {"GOAL_TEAMS_INSTALL_FAIL_AT": "after_switch"}):
            code, text = self.run_cli()
        self.assertEqual(code, 1, text)
        self.assertEqual(snapshot(self.home), {"agents": "dir"})
        self.assertEqual(snapshot(self.user_home), {}, "the skills folder made for the lock is taken back")

    def test_lock_blocks_concurrent_install_and_stale_lock_is_replaced(self):
        lock = os.path.join(self.home, ".goal-teams-install.lock")
        write(lock, "{}")  # no pid to check: only its age tells
        code, text = self.run_cli()
        self.assertEqual(code, 2, text)
        self.assertIn("another install is running", text)
        old = time.time() - 11 * 60
        os.utime(lock, (old, old))
        self.assertIn("removing stale lock", self.ok())
        self.assertFalse(os.path.exists(lock))

    def test_lock_next_to_the_target_is_shared_by_homes_that_install_into_the_same_folder(self):
        other = os.path.join(self.tmp, "other-home")  # e.g. another $CODEX_HOME: same ~/.agents/skills
        skills = os.path.join(self.user_home, ".agents", "skills")
        skills_lock = os.path.join(skills, ".goal-teams-install.lock")
        for home in (self.home, other):
            self.assertEqual(install.Target("codex", home).locks, [os.path.join(home, ".goal-teams-install.lock"),
                                                                   skills_lock])
        with install.locked(install.Target("codex", other), skills_lock, install.Out(True)):
            held = json.loads(read(skills_lock))
            self.assertEqual((held["pid"], held["home"], held["target"]), (os.getpid(), other, self.skill))
            for home in (self.home, other):
                code, text = self.run_cli(home=home)
                self.assertEqual(code, 2, text)
                self.assertIn(f"another install is running (lock {skills_lock}, pid {os.getpid()}, ", text)
                self.assertFalse(os.path.lexists(os.path.join(home, ".goal-teams-install.lock")), "home lock released")
            self.assertFalse(os.path.lexists(self.skill))
        self.assertFalse(os.path.lexists(skills_lock))
        self.ok()
        self.ok(home=other)  # takes turns with the first home: its backup of the shared skill lands in its own home
        self.assertEqual(len(os.listdir(os.path.join(other, "goal-teams-backups"))), 1)
        for home in (self.home, other):
            self.assertIn("verify: OK", self.ok("--verify", home=home))
        self.assertEqual(sorted(os.listdir(skills)), ["goal-teams"], "no lock left behind")
        link = os.path.join(self.tmp, "skills-link")
        try:
            os.symlink(skills, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            return  # symlinks are not available: the real-path keying is not testable here
        self.assertEqual(install.Target("codex", other, link).locks[1], skills_lock, "keyed by the real path")

    def test_lock_of_a_finished_process_is_stale_but_a_live_one_blocks_whatever_its_age(self):
        skills_lock = install.Target("codex", self.home).locks[1]
        for lock in (os.path.join(self.home, ".goal-teams-install.lock"), skills_lock):
            write(lock, json.dumps({"pid": dead_pid(), "started_at": "2000-01-01T00:00:00Z"}))
            text = self.ok()
            self.assertIn(f"removing stale lock {lock} (process ", text)
            self.assertFalse(os.path.exists(lock))
        write(skills_lock, json.dumps({"pid": os.getpid(), "started_at": "2000-01-01T00:00:00Z"}))
        old = time.time() - 11 * 60
        os.utime(skills_lock, (old, old))
        code, text = self.run_cli()
        self.assertEqual(code, 2, text)
        self.assertIn(f"another install is running (lock {skills_lock}, pid {os.getpid()}, ", text)
        self.assertTrue(os.path.exists(skills_lock), "a lock of a live process is never removed")
        self.assertIn("verify: OK", self.ok("--verify"))

    def test_two_homes_installing_into_one_folder_at_once_take_turns_and_keep_their_staging_copies(self):
        other = os.path.join(self.tmp, "other-home")
        skills = os.path.join(self.user_home, ".agents", "skills")
        lock, flag = os.path.join(skills, ".goal-teams-install.lock"), os.path.join(self.tmp, "go")
        argv = [sys.executable, INSTALL_PY, "--host", "codex", "--source", self.src]
        first = subprocess.Popen(argv, env=self.sub_env(GOAL_TEAMS_INSTALL_WAIT_AT=f"staged:{flag}"),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(first.kill)
        self.addCleanup(write, flag, "")
        staging = os.path.join(skills, f".skill{install.STAGING}{first.pid}")
        deadline = time.time() + 30
        while time.time() < deadline and not ((install.read_json(lock) or {}).get("pid") == first.pid
                                              and os.path.isfile(os.path.join(staging, ".goal-teams-install.json"))):
            time.sleep(0.05)
        self.assertEqual((install.read_json(lock) or {}).get("pid"), first.pid, "the first run holds the lock")
        self.assertTrue(os.path.isdir(staging), "and has staged its copy")
        second = subprocess.run(argv, env=self.sub_env(CODEX_HOME=other), capture_output=True, text=True)
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        self.assertIn(f"another install is running (lock {lock}, pid {first.pid}, ", second.stderr)
        self.assertTrue(os.path.isdir(staging), "the refused run must not touch the running one's staging copy")
        self.assertFalse(os.path.lexists(self.skill))
        self.assertFalse(os.path.lexists(other), "the refused run leaves nothing behind")
        write(flag, "")
        out, err = first.communicate(timeout=60)
        self.assertEqual(first.returncode, 0, out + err)
        self.assertIn("installed Goal Teams 3.0.0 for codex", out)
        second = subprocess.run(argv, env=self.sub_env(CODEX_HOME=other), capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("backup of the previous state", second.stdout)
        for home in (self.home, other):
            res = subprocess.run([*argv[:4], "--verify"], env=self.sub_env(CODEX_HOME=home),
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("verify: OK", res.stdout)
            self.assertEqual(sorted(os.listdir(os.path.join(home, "agents"))),
                             ["goal_backend.toml", "goal_reviewer.toml"])
        self.assertEqual(sorted(os.listdir(skills)), ["goal-teams"], "no lock and no staging copy left behind")

    # -------------------------------------------------------------- hosts and homes
    def test_default_host_and_home_detection(self):
        self.assertEqual(install.pick_hosts(None)[0], ["codex"])
        os.makedirs(os.path.join(self.user_home, ".claude"))
        self.assertEqual(install.pick_hosts(None)[0], ["claude"])
        os.makedirs(os.path.join(self.user_home, ".codex"))
        self.assertEqual(install.pick_hosts(None)[0], ["codex"])
        self.assertEqual(install.pick_hosts("both")[0], ["codex", "claude"])
        custom = os.path.join(self.tmp, "custom-codex")
        with mock.patch.dict(os.environ, {"CODEX_HOME": custom}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = install.main(["--dry-run", "--source", self.src])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn(f"== codex: {custom}", out.getvalue())
        self.assertIn(f"target: {self.skill} (now: nothing)", out.getvalue())
        self.assertIn("auto", out.getvalue())
        self.assertFalse(os.path.exists(custom))

    def test_other_host_install_in_same_home_is_refused(self):
        self.ok(host="claude")  # its skill folder <home>/skills/goal-teams is the old Codex location
        before = snapshot(self.tmp)
        for args in ([], ["--skills-dir", os.path.join(self.home, "skills")]):
            code, text = self.run_cli(*args)
            self.assertEqual(code, 2, text)
            self.assertIn("holds the claude install", text)
        text = self.ok("--uninstall")  # codex leaves the claude install alone, and says so
        self.assertIn("nothing to uninstall", text)
        self.assertIn("it is the claude install, so it is left alone", text)
        self.assertEqual(snapshot(self.tmp), before)
        self.ok("--verify", host="claude")

    @unittest.skipUnless(GIT, "git is not installed")
    def test_source_git_commit_and_dirty_flag_are_recorded(self):
        self.git(self.src, "init", "-q")
        self.git(self.src, "add", "-A")
        self.git(self.src, "commit", "-qm", "source")
        head = self.git(self.src, "rev-parse", "HEAD").strip()
        self.ok()
        self.assertEqual(self.manifest()["source"]["commit"], head)
        self.assertIs(self.manifest()["source"]["dirty"], False)
        write(os.path.join(self.src, "plugins", "goal-teams", "skills", "goal-teams", "rules", "core.md"), "wip\n")
        self.ok()
        self.assertIs(self.manifest()["source"]["dirty"], True)

    # -------------------------------------------------------------- the script itself
    def test_script_runs_standalone_with_json_and_help(self):
        res = self.run_script("--host", "codex", "--home", self.home, "--source", self.src, "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["hosts"][0]["version"], "3.0.0")
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        for text in ("Usage:", "--rollback", "--skills-dir", "~/.agents/skills/goal-teams/", "old skills location",
                     "managed install", "unmanaged directory", "your own changes", ".goal-teams-install.lock"):
            self.assertIn(text, res.stdout)

    def test_installer_parses_as_python39(self):
        with open(INSTALL_PY, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 9))

    def test_installer_wording_is_version_free(self):
        """A manifest-based install is a 'managed install', anything else an 'unmanaged directory': no product
        version numbers in messages or docstrings (the manifest schema and file name stay as they are)."""
        with open(INSTALL_PY, encoding="utf-8") as f:
            text = f.read()
        self.assertNotRegex(text, r"(?i)\b(?:non-)?v\d")
        self.assertIn('"goal-teams/install@1"', text)
        self.assertIn('".goal-teams-install.json"', text)


if __name__ == "__main__":
    unittest.main()
