#!/usr/bin/env python3
"""Repository checks for Goal Teams. Run before every commit; CI runs it on every push.

  python3 tools/check.py          # all checks, exit 1 on any failure
  python3 tools/check.py --list   # list check names

What it guards (the V2 failure modes this repository must not grow back):
  - generated files drifting from their single sources (members, VERSION)
  - context cost: per-file byte budgets and per-route token budgets
  - "copy is a version": versioned directories or files in the tree
  - stale version strings, absolute local paths or test data inside the shipped package
  - SKILL.md format: frontmatter, description, route table equal to the gt route table
  - duplicate rule IDs and references to rule/template files that do not exist
  - Python 3.9 syntax compatibility and valid JSON manifests
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Callable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "goal-teams"
SKILL = PLUGIN / "skills" / "goal-teams"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

ALLOWED_TOP = {
    ".agents", ".claude-plugin", ".github", ".gitignore", "AGENTS.md", "CHANGELOG.md", "LICENSE",
    "MIGRATION.md", "README.md", "README.en.md", "VERSION", "examples", "extras", "goal-teams.md",
    "keys", "members", "plugins", "tests", "tools",
}
# Bytes. The Lead reads SKILL.md plus the route's rule files; V2.9 keeps direct within 8 KB and
# tracked within 14 KB of raw bytes (domain add-ons, member packets and resume are reported separately).
FILE_BUDGETS = {
    "SKILL.md": 4096, "rules/work.md": 4096, "rules/tracked.md": 6144,
    "rules/release.md": 4500, "rules/ui.md": 6000, "rules/agent-dev.md": 4500,
}
TEMPLATE_BUDGET = 2600
AGENT_BUDGET = 4300
ROUTE_BYTE_BUDGETS = {"direct": 8 * 1024, "tracked": 14 * 1024}
ADDON_TOKEN_BUDGET = 20000
VERSIONED_SEGMENT = re.compile(r"^(?:[vV]\d+(?:\.\d+)+|v\d{2,})(?:$|[._-])")
ANY_VERSION = re.compile(r"\bV(\d+)\.(\d+)\b")  # product versions are written V2.7; eval fixtures use v1.0 tags


def display_version() -> str:
    major, minor = (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:2]
    return "V%s.%s" % (major, minor)


def stale_version(text: str) -> "Optional[str]":
    """A product version string in shipped text that is not the current one (V2.68, V3.0, ...)."""
    current = display_version()
    for match in ANY_VERSION.finditer(text):
        token = "V%s.%s" % (match.group(1), match.group(2))
        if token != current:
            return match.group(0)
    return None
ABSOLUTE_PATH = re.compile(r"(?:/home/[a-z]|/Users/[A-Za-z]|[A-Z]:\\\\Users|/tmp/claude)")
# Shipped files that name other versions on purpose (experiment groups, migration maps); everything
# else in the package must only carry the current version.
VERSION_HISTORY_FILES = {"plugins/goal-teams/evals/comparison.md"}

Result = Tuple[bool, List[str]]


def tracked_files() -> List[str]:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                             capture_output=True, check=True).stdout.decode("utf-8").strip()
        if Path(top).resolve() != ROOT.resolve():
            # An extracted source tree can live in an ignored directory of another repo.
            # That parent's successful, empty ls-files is not an inventory of this source.
            raise ValueError("source directory is not the Git worktree root")
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
        return sorted(p for p in out.split("\0") if p and (ROOT / p).exists())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                      if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)


def tokens(text: str) -> int:
    """Estimated tokens, calibrated against Claude Code's own estimate (plugin details)."""
    cjk = len(re.findall(r"[　-鿿＀-￯]", text))
    return int(cjk * 1.4 + (len(text) - cjk) / 3.6)


# --------------------------------------------------------------------------- checks
def check_generated() -> Result:
    import gen
    try:
        outputs = gen.planned_outputs()
    except gen.GenError as exc:
        return False, [str(exc)]
    stale = [p.relative_to(ROOT).as_posix() for p, text in outputs.items()
             if not p.is_file() or p.read_text(encoding="utf-8") != text]
    stale += ["orphan: " + p.relative_to(ROOT).as_posix() for p in gen.stale_generated(outputs)]
    return (not stale), (["run python3 tools/gen.py"] + stale if stale else ["%d generated files current" % len(outputs)])


def frontmatter(text: str) -> Tuple[dict, str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}, text
    head, body = text[4:].split("\n---\n", 1)
    data = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data, body


def check_skill_md() -> Result:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    meta, body = frontmatter(text)
    problems = []
    if set(meta) != {"name", "description"}:
        problems.append("frontmatter must contain exactly name and description (Codex rule), got %s" % sorted(meta))
    if meta.get("name") != "goal-teams":
        problems.append("name must be goal-teams")
    description = meta.get("description", "")
    if not 50 <= len(description) <= 1024:
        problems.append("description must be 50..1024 chars (got %d)" % len(description))
    if ANY_VERSION.search(description):
        problems.append("description must not contain a version number")
    if description.startswith(("我", "I ")):
        problems.append("description must be written in the third person")
    for word in ("Goal Teams", "$goal-teams"):
        if word not in description:
            problems.append("description should mention the trigger %r" % word)
    lines = text.count("\n")
    if lines > 500:
        problems.append("SKILL.md has %d lines (limit 500)" % lines)
    return not problems, problems or ["frontmatter ok, %d lines" % lines]


def skill_route_table() -> dict:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    table = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].split("（")[0] in ("discussion", "direct", "tracked"):
            table[cells[0].split("（")[0]] = cells[2]
    return table


def check_route_table() -> Result:
    from goalteams import routes
    table = skill_route_table()
    problems = []
    for mode in ("discussion", "direct", "tracked"):
        cell = table.get(mode)
        if cell is None:
            problems.append("SKILL.md route table has no row for %s" % mode)
            continue
        listed = [part.strip() for part in cell.split(",") if part.strip() and not part.strip().startswith("—")]
        if listed != routes.BASE_RULES[mode]:
            problems.append("%s: SKILL.md lists %s but gt route uses %s" % (mode, listed, routes.BASE_RULES[mode]))
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for flag, rule in routes.ADDON_RULES.items():
        if rule not in text:
            problems.append("SKILL.md does not mention add-on rule %s (%s)" % (rule, flag))
    return not problems, problems or ["SKILL.md route table == gt route table"]


def check_budgets() -> Result:
    from goalteams import routes
    problems, notes = [], []
    sizes = {}
    for rel, budget in FILE_BUDGETS.items():
        path = SKILL / rel
        if not path.is_file():
            problems.append("missing %s" % rel)
            continue
        text = path.read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        sizes[rel] = tokens(text)
        if size > budget:
            problems.append("%s is %d bytes (budget %d)" % (rel, size, budget))
    for path in sorted((SKILL / "templates").glob("*.md")):
        size = path.stat().st_size
        if size > TEMPLATE_BUDGET:
            problems.append("templates/%s is %d bytes (budget %d)" % (path.name, size, TEMPLATE_BUDGET))
    for path in sorted((PLUGIN / "agents").glob("*.md")):
        size = path.stat().st_size
        if size > AGENT_BUDGET:
            problems.append("agents/%s is %d bytes (budget %d)" % (path.name, size, AGENT_BUDGET))
    byte_sizes = {rel: (SKILL / rel).stat().st_size for rel in FILE_BUDGETS if (SKILL / rel).is_file()}
    for mode, budget in ROUTE_BYTE_BUDGETS.items():
        files = ["SKILL.md"] + routes.BASE_RULES[mode]
        total = sum(byte_sizes.get(f, 0) for f in files)
        notes.append("%s route = %d bytes ≈ %d tokens (budget %d bytes)" % (
            mode, total, sum(sizes.get(f, 0) for f in files), budget))
        if total > budget:
            problems.append("%s route is %d bytes (budget %d)" % (mode, total, budget))
    full = ["SKILL.md"] + routes.BASE_RULES["tracked"] + list(routes.ADDON_RULES.values())
    total = sum(sizes.get(f, 0) for f in full)
    notes.append("tracked + all add-ons ≈ %d tokens (budget %d)" % (total, ADDON_TOKEN_BUDGET))
    if total > ADDON_TOKEN_BUDGET:
        problems.append("tracked route with every add-on is ≈%d tokens (budget %d)" % (total, ADDON_TOKEN_BUDGET))
    return not problems, problems + notes


def check_layout() -> Result:
    files = tracked_files()
    problems = []
    tops = sorted({f.split("/", 1)[0] for f in files} - ALLOWED_TOP)
    if tops:
        problems.append("unexpected top-level entries (add them to ALLOWED_TOP only with a reason): %s"
                        % ", ".join(tops[:20]))
    versioned = sorted({f for f in files for part in f.split("/")[:-1] if VERSIONED_SEGMENT.match(part)})
    if versioned:
        problems.append("versioned directories are not allowed (history lives in git tags): %s"
                        % ", ".join(versioned[:10]))
    # D2: maintainer-local areas never enter git, the package or an install.
    local_only = sorted(f for f in files if f.startswith(("docs/", "develops/")))
    if local_only:
        problems.append("docs/ and develops/ are local-only and must not be tracked: %s" % ", ".join(local_only[:10]))
    shipped = [f for f in files if f.startswith("plugins/goal-teams/")]
    test_like = [f for f in shipped if re.search(r"(^|/)(tests?|fixtures)/", f[len("plugins/goal-teams/"):])
                 and "/evals/" not in f]
    if test_like:
        problems.append("tests or fixtures inside the shipped package: %s" % ", ".join(test_like[:10]))
    big = [f for f in shipped if (ROOT / f).stat().st_size > 64 * 1024]
    if big:
        problems.append("files over 64 KB in the shipped package: %s" % ", ".join(big))
    return not problems, problems or ["%d files, %d shipped" % (len(files), len(shipped))]


def check_shipped_text() -> Result:
    problems = []
    for rel in tracked_files():
        if not rel.startswith("plugins/goal-teams/") or not rel.endswith((".md", ".py", ".json", ".toml", ".yaml", ".sh")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        stale = None if rel in VERSION_HISTORY_FILES else stale_version(text)
        if stale:
            problems.append("%s: stale version string %r (current is %s)" % (rel, stale, display_version()))
        if ABSOLUTE_PATH.search(text):
            problems.append("%s: absolute local path %r" % (rel, ABSOLUTE_PATH.search(text).group(0)))
        if "Banchmark" in text and "/evals/" not in rel:  # eval graders may assert its absence
            problems.append("%s: use Benchmark (V2 spelling Banchmark)" % rel)
    return not problems, problems or ["shipped text clean"]


def check_rule_ids() -> Result:
    seen = {}
    problems = []
    for path in sorted((SKILL / "rules").glob("*.md")):
        for rule_id in re.findall(r"\*\*(GT-[A-Z]+(?:-[A-Z0-9]+)+)\*\*", path.read_text(encoding="utf-8")):
            if rule_id in seen:
                problems.append("%s defined in %s and %s" % (rule_id, seen[rule_id], path.name))
            seen[rule_id] = path.name
    return not problems, problems or ["%d unique rule IDs" % len(seen)]


def check_references() -> Result:
    problems = []
    sources = [SKILL / "SKILL.md", *sorted((SKILL / "rules").glob("*.md")), *sorted((SKILL / "templates").glob("*.md")),
               *sorted((ROOT / "members").glob("*.md"))]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for ref in sorted(set(re.findall(r"\b((?:rules|templates)/[a-z0-9-]+\.md)", text))):
            if not (SKILL / ref).is_file():
                problems.append("%s references missing %s" % (source.relative_to(ROOT).as_posix(), ref))
    return not problems, problems or ["all rule/template references exist"]


def check_python() -> Result:
    problems = []
    roots = [PLUGIN, ROOT / "tools", ROOT / "tests", ROOT / "extras"]
    count = 0
    for base in roots:
        for path in sorted(base.rglob("*.py")) if base.is_dir() else []:
            if "__pycache__" in path.parts:
                continue
            count += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))
            except SyntaxError as exc:
                problems.append("%s: not Python 3.9 compatible: %s" % (path.relative_to(ROOT), exc))
    return not problems, problems or ["%d Python files parse as 3.9" % count]


def check_manifests() -> Result:
    problems = []
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    for rel in (".claude-plugin/marketplace.json", "plugins/goal-teams/.claude-plugin/plugin.json",
                "plugins/goal-teams/hooks/hooks.json"):
        try:
            data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append("%s: %s" % (rel, exc))
            continue
        if rel.endswith("plugin.json") and data.get("version") != version:
            problems.append("plugin.json version %s != VERSION %s" % (data.get("version"), version))
        if rel.endswith("marketplace.json"):
            for entry in data.get("plugins", []):
                source = entry.get("source", "")
                if isinstance(source, str) and not (ROOT / source).is_dir():
                    problems.append("marketplace source %s does not exist" % source)
    major, minor = version.split(".")[:2]
    display = "V%s.%s" % (major, minor)
    for readme in ("README.md", "README.en.md"):
        text = (ROOT / readme).read_text(encoding="utf-8")
        block = text.split("<!-- goal-teams-release:start -->", 1)[-1].split("<!-- goal-teams-release:end -->", 1)[0]
        if display not in block:
            problems.append("%s release block does not show %s (run python3 tools/gen.py)" % (readme, display))
    return not problems, problems or ["manifests valid, version %s" % version]


def check_acceptance() -> Result:
    """tests/acceptance.json: 36 fixed risks, known statuses, every named test exists (tools/acceptance.py)."""
    import acceptance
    data = acceptance.load()
    problems = acceptance.validate(data)
    counts = {}
    for item in data["items"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    summary = ", ".join("%s=%d" % kv for kv in sorted(counts.items()))
    return not problems, problems or ["%d items (%s); run tools/acceptance.py --run to settle" % (len(data["items"]), summary)]


CHECKS: List[Tuple[str, Callable[[], Result]]] = [
    ("generated", check_generated),
    ("acceptance", check_acceptance),
    ("skill-md", check_skill_md),
    ("route-table", check_route_table),
    ("budgets", check_budgets),
    ("layout", check_layout),
    ("shipped-text", check_shipped_text),
    ("rule-ids", check_rule_ids),
    ("references", check_references),
    ("python39", check_python),
    ("manifests", check_manifests),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("only", nargs="*", help="run only these checks")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(name for name, _ in CHECKS))
        return 0
    failed = 0
    for name, check in CHECKS:
        if args.only and name not in args.only:
            continue
        try:
            ok, details = check()
        except Exception as exc:  # a crashing check is a failing check
            ok, details = False, ["%s: %s" % (type(exc).__name__, exc)]
        print("%s %s" % ("✔" if ok else "✘", name))
        for line in details:
            print("    %s" % line)
        failed += 0 if ok else 1
    print("\n%s" % ("all checks passed" if not failed else "%d check(s) failed" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
