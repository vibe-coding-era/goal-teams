"""Environment preflight (replaces the mandatory preflight subagent for small work)."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from . import gitinfo
from .ledger import Project


def detect_runners(root: Path) -> List[str]:
    found: List[str] = []
    def has(*names: str) -> bool:
        return any((root / n).exists() for n in names)
    if has("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "conftest.py") or (root / "tests").is_dir():
        found.append("python: pytest" if shutil.which("pytest") or has("pytest.ini", "conftest.py")
                     else "python: unittest")
    package = root / "package.json"
    if package.is_file():
        try:
            import json
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except ValueError:
            scripts = {}
        manager = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "npm"
        if "test" in scripts:
            found.append("node: %s test" % manager)
        if any("playwright" in str(v) for v in scripts.values()) or has("playwright.config.ts", "playwright.config.js"):
            found.append("e2e: playwright")
    if has("go.mod"):
        found.append("go: go test ./...")
    if has("Cargo.toml"):
        found.append("rust: cargo test")
    if has("pom.xml"):
        found.append("java: mvn test")
    if has("build.gradle", "build.gradle.kts"):
        found.append("java: gradle test")
    if has("Makefile"):
        try:
            if "\ntest:" in "\n" + (root / "Makefile").read_text(encoding="utf-8", errors="replace"):
                found.append("make test")
        except OSError:
            pass
    return found


def run(project: Project) -> Dict[str, Any]:
    work = project.work_tree
    info: Dict[str, Any] = {
        "python": platform.python_version(),
        "platform": "%s %s" % (platform.system(), platform.machine()),
        "root": str(project.root),
        "work_tree": str(work),
        "state_dir": project.exists(),
        "writable": os.access(str(project.root), os.W_OK),
        "git": None,
        "runners": detect_runners(work),
        "warnings": [],
        "blockers": [],
    }
    if sys.version_info < (3, 9):
        info["blockers"].append("需要 Python 3.9+")
    if not info["writable"]:
        info["blockers"].append("项目目录不可写")
    if gitinfo.git_available() and gitinfo.is_repo(work):
        counts = gitinfo.status_counts(work)
        branch = gitinfo.branch(work)
        default = gitinfo.default_branch(work)
        info["git"] = {
            "head": gitinfo.head(work),
            "branch": branch,
            "default_branch": default,
            "changed": counts["changed"],
            "untracked": counts["untracked"],
            "remotes": gitinfo.remotes(work),
            "linked_worktree": gitinfo.is_linked_worktree(work),
        }
        git_conf = (project.config().get("git") or {}) if project.exists() else {}
        if branch and default and branch == default and git_conf.get("branch", "feature") == "feature":
            info["warnings"].append("当前在默认分支 %s：提交前先建功能分支，例如 %s<主题>"
                                    "（不需要时：gt config set git.branch current）" % (
                                        branch, git_conf.get("branch_prefix", "goal/")))
        if branch is None:
            info["warnings"].append("HEAD 处于分离状态")
        wanted = git_conf.get("remote_protocol", "inherit")
        for remote in info["git"]["remotes"]:
            if wanted in ("ssh", "https") and remote["protocol"] in ("ssh", "https") and remote["protocol"] != wanted:
                info["warnings"].append("remote %s 用的是 %s，项目约定 %s（gt 不会改 remote）" % (
                    remote["name"], remote["protocol"], wanted))
        hidden = gitinfo.hidden_changes(work)
        if hidden:
            info["warnings"].append("%d 个文件被设为 assume-unchanged/skip-worktree，gt diff 看不到它们的改动" % len(hidden))
        exclude = Path(gitinfo._out(["rev-parse", "--git-path", "info/exclude"], work) or "")
        exclude = exclude if exclude.is_absolute() else work / exclude
        try:
            entries = [x for x in exclude.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
        except OSError:
            entries = []
        if entries:
            info["warnings"].append(".git/info/exclude 里有 %d 条忽略规则：被它忽略的新文件不会出现在 gt diff 中" % len(entries))
        if info["git"]["linked_worktree"] and (gitinfo.toplevel(work) or work) != project.root \
                and ((gitinfo.toplevel(work) or work) / ".goal-teams" / "config.json").is_file():
            info["warnings"].append("这个工作树里有一份被提交的 .goal-teams/：gt 以主项目的状态为准，忽略它")
        if counts["changed"] or counts["untracked"]:
            info["warnings"].append("工作区有未提交改动：%d 修改、%d 未跟踪（gt diff 会把它们算进本目标）" % (
                counts["changed"], counts["untracked"]))
    elif not gitinfo.git_available():
        info["warnings"].append("没有 git：gt diff 不可用，源码摘要改用文件遍历")
    else:
        info["warnings"].append("不是 git 仓库：gt diff 不可用，源码摘要改用文件遍历")
    if not info["runners"]:
        info["warnings"].append("没有识别到测试命令：请在任务包里写明验证命令")
    return info


def format_text(info: Dict[str, Any]) -> str:
    lines = ["环境预检（gt doctor）",
             "- Python %s · %s" % (info["python"], info["platform"]),
             "- 项目根：%s%s" % (info["root"], "" if info["work_tree"] == info["root"] else "（工作树 %s）" % info["work_tree"]),
             "- 状态目录：%s" % ("已初始化" if info["state_dir"] else "未初始化（gt init）")]
    git = info.get("git")
    if git:
        remotes = ", ".join("%s(%s)" % (r["name"], r["protocol"]) for r in git["remotes"]) or "无"
        lines.append("- git：分支 %s（默认 %s）· 修改 %d · 未跟踪 %d · remote：%s%s" % (
            git["branch"] or "detached", git["default_branch"] or "?", git["changed"], git["untracked"], remotes,
            " · 链接工作树" if git["linked_worktree"] else ""))
    lines.append("- 测试命令：%s" % ("、".join(info["runners"]) or "未识别"))
    for item in info["blockers"]:
        lines.append("✘ %s" % item)
    for item in info["warnings"]:
        lines.append("⚠ %s" % item)
    if not info["blockers"]:
        lines.append("✔ 可以开始")
    return "\n".join(lines)
