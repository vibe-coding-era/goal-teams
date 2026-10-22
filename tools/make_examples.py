#!/usr/bin/env python3
"""Regenerate examples/ by running a scripted Goal Teams session with the real gt CLI.

  python3 tools/make_examples.py           # rewrite examples/*.md
  python3 tools/make_examples.py --check   # exit 1 if examples/ is out of date (CI)

Everything under examples/ except README.md is produced here, so the examples can
never drift from what gt actually prints.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "plugins" / "goal-teams" / "skills" / "goal-teams" / "scripts" / "gt.py"
OUT = ROOT / "examples"

CART_BUGGY = '''def total(prices, discount_percent=0):
    """Sum prices and apply a percentage discount."""
    subtotal = sum(prices)
    return subtotal - discount_percent
'''
CART_FIXED = '''def total(prices, discount_percent=0):
    """Sum prices and apply a percentage discount (0-100)."""
    if not 0 <= discount_percent <= 100:
        raise ValueError("discount_percent must be between 0 and 100")
    subtotal = sum(prices)
    return round(subtotal * (100 - discount_percent) / 100, 2)
'''
TEST_BASE = '''import sys
import unittest

sys.path.insert(0, "src")
from cart import total


class TotalTests(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(total([10, 5]), 15)
'''
TEST_NEW = TEST_BASE + '''
    def test_percent_discount(self):
        self.assertEqual(total([100, 50], discount_percent=10), 135)

    def test_rejects_out_of_range_discount(self):
        with self.assertRaises(ValueError):
            total([10], discount_percent=120)
'''
README_BASE = "# shop\n\n`total(prices)` 返回价格之和。\n"
README_NEW = README_BASE + "\n`total(prices, discount_percent)` 按百分比打折（0–100），超出范围抛出 ValueError。\n"
# "python3" from PATH (examples are compared on Linux), so the recorded commands do not depend on the
# interpreter that runs this script; elsewhere fall back to it.
UNITTEST = [("python3" if shutil.which("python3") else sys.executable), "-m", "unittest", "-q", "tests.test_cart"]


class Session:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.env = dict(os.environ, GT_NOW="2026-10-18T08:00:00Z", GT_FIXED_DURATION_MS="120",
                        PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_DATE="2026-10-18T08:00:00Z",
                        GIT_COMMITTER_DATE="2026-10-18T08:00:00Z")
        self.env.pop("GT_ACTOR", None)

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, env=self.env)

    def gt(self, *args: str, ok: bool = True) -> str:
        result = subprocess.run([sys.executable, str(GT), *args], cwd=self.root, capture_output=True, text=True,
                                encoding="utf-8", env=self.env)
        if ok and result.returncode != 0:
            raise SystemExit("gt %s failed:\n%s\n%s" % (" ".join(args), result.stdout, result.stderr))
        return result.stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def scenario(work: Path) -> Dict[str, str]:
    root = work / "shop"
    root.mkdir()
    s = Session(root)
    s.write("src/cart.py", CART_BUGGY)
    s.write("tests/__init__.py", "")
    s.write("tests/test_cart.py", TEST_BASE)
    s.write("README.md", README_BASE)
    s.write(".gitignore", "__pycache__/\n")
    s.git("init", "-q", "-b", "main")
    s.git("config", "user.name", "example")
    s.git("config", "user.email", "example@example.invalid")
    s.git("remote", "add", "origin", "https://github.com/example/shop.git")
    s.git("add", "-A")
    s.git("commit", "-qm", "init")
    s.git("switch", "-q", "-c", "goal/cart-discount")

    s.gt("init")
    s.gt("goal", "购物车折扣计算修复", "--mode", "tracked", "--rounds", "2",
         "--done", "total() 按百分比折扣计算，并拒绝 0–100 之外的折扣", "--check", " ".join(UNITTEST),
         "--done", "README 写明折扣参数")
    s.write(".goal-teams/plan.json", json.dumps({"tasks": [
        {"id": "T1", "title": "折扣计算修复", "owner": "goal_backend", "validator": "goal_reviewer", "priority": "P0",
         "scope": ["src/cart.py", "tests/test_cart.py"], "accept": "子任务全部验收", "exit": "T1.1、T1.2 已验收"},
        {"id": "T1.1", "title": "补折扣边界测试", "parent": "T1", "kind": "test", "owner": "goal_unit_test_designer",
         "validator": "goal_reviewer", "scope": ["tests/test_cart.py"], "accept": "覆盖百分比折扣与越界折扣",
         "exit": "测试能暴露当前缺陷",
         "exit_condition": {"required_receipt_types": ["review"], "on_budget_exhaustion": "blocked"}},
        {"id": "T1.2", "title": "修复折扣实现", "parent": "T1", "tdd": True, "deps": ["T1.1"], "owner": "goal_backend",
         "validator": "goal_reviewer", "scope": ["src/cart.py"], "accept": "total([100,50],10)==135；120 抛 ValueError",
         "exit": "Green 且受影响测试通过"},
        {"id": "T2", "title": "更新 README 折扣说明", "kind": "doc", "deps": ["T1.2"], "owner": "goal_docs",
         "validator": "goal_reviewer", "artifacts": ["README.md"], "scope": ["README.md"],
         "accept": "README 写明折扣参数与取值范围"},
    ]}, ensure_ascii=False, indent=2))
    plan = s.gt("plan", "apply")

    # round 1: tests written and reviewed, Red recorded; implementation still in progress.
    s.gt("task", "start", "T1.1", "--as", "goal_unit_test_designer")
    s.write("tests/test_cart.py", TEST_NEW)
    s.gt("task", "done", "T1.1", "--as", "goal_unit_test_designer")
    s.gt("review", "T1.1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "覆盖正常折扣与越界")
    s.gt("tdd", "red", "T1.2", "--test", "tests/test_cart.py", "--expect", "AssertionError|ValueError not raised",
         "--as", "goal_unit_test_runner", "--", *UNITTEST)
    s.gt("loop", "decide", "continue", "--next", "实现折扣修复让 T1.2 变绿，再更新 README",
         "--reason", "测试已暴露缺陷（Red 成立）")
    round1 = s.gt("report", "--summary",
                  "补充了折扣边界测试并通过评审；Red 已确认当前实现把折扣当作金额相减。实现尚未开始，README 未更新。")
    resume = s.gt("resume")

    # round 2: Green, reviews, README, completion.
    s.write("src/cart.py", CART_FIXED)
    s.gt("tdd", "green", "T1.2", "--as", "goal_unit_test_runner", "--", *UNITTEST)
    s.gt("task", "done", "T1.2", "--as", "goal_backend")
    s.gt("review", "T1.2", "--by", "goal_reviewer", "--verdict", "pass", "--note", "百分比计算与范围校验正确")
    s.gt("task", "done", "T1")
    s.gt("task", "start", "T2", "--as", "goal_docs")
    s.write("README.md", README_NEW)
    s.gt("task", "done", "T2", "--as", "goal_docs")
    s.write(".goal-teams/reviews.json", json.dumps([
        {"task": "T1", "by": "goal_reviewer", "verdict": "pass", "note": "子任务均已验收"},
        {"task": "T2", "by": "goal_reviewer", "verdict": "pass", "note": "说明与实现一致"},
    ], ensure_ascii=False, indent=2))
    s.gt("review", "--file", ".goal-teams/reviews.json")
    s.gt("goal", "accept", "--item", "C2", "--result", "pass", "--quote", "用户：README 的折扣说明可以了")
    s.gt("reflect", "测试先行暴露了把百分比当金额的缺陷", "--kind", "stop",
         "--action", "在任务包里写明 --expect 的失败特征，避免假 Red")
    finish = s.gt("finish")  # re-runs the Green on the final code (README changed after it), runs C1's --check, records achieved
    check = s.gt("check")
    final = s.gt("report", "--summary",
                 "折扣按百分比计算并拒绝越界值；Red→Green 证据齐全，三项任务均已由 goal_reviewer 验收，README 已更新。"
                 "未做：发布与线上验证。")
    six = s.gt("report", "--format", "six", "--summary",
               "折扣按百分比计算并拒绝越界值；Red→Green 证据齐全，三项任务均已由 goal_reviewer 验收，README 已更新。"
               "未做：发布与线上验证。")
    english = s.gt("report", "--lang", "en", "--summary",
                   "Discount is now percentage based and range checked; all tasks accepted. Not done: release.")
    state = root / ".goal-teams"
    return {
        "tracked-plan-apply.txt": plan,
        "tracked-round1-report.md": round1,
        "tracked-resume.md": resume,
        "tracked-finish.txt": finish,
        "tracked-final-report.md": final,
        "tracked-final-report.six.md": six,
        "tracked-final-report.en.md": english,
        "tracked-check.txt": check,
        "TaskList.md": (state / "TaskList.md").read_text(encoding="utf-8"),
        "benchmark.md": (state / "benchmark.md").read_text(encoding="utf-8"),
        "loop-review.md": (state / "loop-review.md").read_text(encoding="utf-8"),
    }


def render(outputs: Dict[str, str]) -> Dict[str, str]:
    files: Dict[str, str] = {}
    for name, text in outputs.items():
        if name not in ("TaskList.md", "benchmark.md", "loop-review.md"):
            title = name.rsplit(".", 1)[0]
            note = "<!-- generated by tools/make_examples.py from a real gt session; do not edit -->\n\n"
            files[name if not name.endswith(".txt") else title + ".md"] = (
                note + "```text\n" + text.rstrip("\n") + "\n```\n" if name.endswith(".txt") else note + text.rstrip("\n") + "\n")
        else:
            files["state/" + name] = text
    return files


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if shutil.which("git") is None:
        print("make_examples: git is required", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="gt-examples-") as tmp:
        files = render(scenario(Path(tmp)))
    stale = []
    for rel, text in files.items():
        path = OUT / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(rel)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
    if args.check:
        if stale:
            print("examples out of date: %s (run python3 tools/make_examples.py)" % ", ".join(stale))
            return 1
        print("examples are up to date (%d files)" % len(files))
        return 0
    print("wrote %d file(s): %s" % (len(stale), ", ".join(stale) or "none changed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
