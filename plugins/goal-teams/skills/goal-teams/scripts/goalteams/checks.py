"""Live evaluations that need the filesystem: review bindings, fresh evidence, scope diff, completion."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import gitinfo
from .ledger import Project
from .models import SPEC_FIELDS, CompletionResult, Snapshot, TaskFacts
from .state import State, Task
from .util import matches_any, normalize_scope, now_iso

__all__ = ["matches_any"]

# Kept for callers that still import them from here; the judge in completion.py owns them.
AUDITORS = ("goal_completion_auditor", "user")
AXIS_KINDS = ("runtime", "business", "release", "install")
__all__ += ["SPEC_FIELDS"]
# Test code and test data never count as a task's implementation, even inside its own scope.
TEST_PATTERNS = ("**/tests/**", "**/test/**", "**/__tests__/**", "**/testdata/**", "**/fixtures/**",
                 "**/test_*.py", "**/*_test.py", "**/*_test.go", "**/*.test.*", "**/*.spec.*", "**/conftest.py")


def code_scopes(state: Optional[State]) -> List[str]:
    """Paths that code and test tasks own, plus test files bound by a Red."""
    if state is None:
        return []
    scopes = [s for t in state.active_tasks() if t.kind in ("code", "test") for s in t.scopes]
    return scopes + state.red_test_files()


class Areas:
    """Which files are generated outputs (left out of digests) and which are test areas."""

    def __init__(self, state: Optional[State], icase: bool, extra_artifacts: Iterable[str] = (),
                 tracked: Optional[Set[str]] = None, work_tree: Optional[Path] = None,
                 current: Optional[Dict[str, str]] = None) -> None:
        self.icase = icase
        active = state.active_tasks() if state is not None else []
        self.tests = [s for t in active if t.kind == "test" for s in t.scopes]
        self.tracked = tracked or set()
        self.extra = {gitinfo.normalize_rel(p) for p in extra_artifacts} - self.tracked
        generated = state.generated() if state is not None else {}
        # A declaration only holds while it is still valid: untracked, not in a code/test scope now,
        # and not a file the project already had when the goal started.
        scopes = code_scopes(state)
        baseline = ((state.goal or {}).get("baseline") or {}).get("head") if state is not None else None
        existed = set(gitinfo.paths_in_commit(work_tree, baseline, generated)) if work_tree and generated else set()
        self.generated = {p: kind for p, kind in generated.items()
                          if p not in self.tracked and p not in existed and not (scopes and matches_any(p, scopes, icase))}
        self.work_tree = work_tree
        self.current = current

    def artifact(self, path: str) -> bool:
        """Declared as produced by a recorded command (build artifact or test output) and still valid."""
        return path in self.extra or path in self.generated

    def test_area(self, path: str) -> bool:
        return matches_any(path, TEST_PATTERNS, self.icase) or \
            (bool(self.tests) and matches_any(path, self.tests, self.icase))


class Live:
    """Per-call cache of the expensive filesystem facts of one work tree."""

    def __init__(self, project: Project, state: Optional[State] = None, extra_artifacts: Iterable[str] = (),
                 ids: Optional[Tuple[Dict[str, str], str]] = None) -> None:
        self.project = project
        self._files: Optional[List[str]] = None
        self._ids = ids
        self._icase: Optional[bool] = None
        self._digests: Dict[Any, str] = {}
        work = project.work_tree
        tracked = set(gitinfo.tracked(work)) if gitinfo.is_repo(work) else set()
        self.areas = Areas(state, self.icase, extra_artifacts, tracked, work, self.ids()[0])

    @property
    def icase(self) -> bool:
        if self._icase is None:
            work = self.project.work_tree
            self._icase = gitinfo.is_repo(work) and gitinfo.ignore_case(work)
        return self._icase

    @property
    def method(self) -> str:
        return self.ids()[1]

    def files(self) -> List[str]:
        if self._files is None:
            self._files = gitinfo.project_files(self.project.work_tree)
        return self._files

    def ids(self) -> Tuple[Dict[str, str], str]:
        if self._ids is None:
            self._ids = gitinfo.tree_ids(self.project.work_tree)
        return self._ids

    def source(self, exclude: Iterable[str] = ()) -> str:
        """Every file except gt state, generated outputs and ``exclude``."""
        skip = frozenset(gitinfo.normalize_rel(p) for p in exclude)
        key = ("source", skip)
        if key not in self._digests:
            areas = self.areas
            self._digests[key] = gitinfo.digest_ids(self.ids()[0], lambda p: p not in skip and not areas.artifact(p))
        return self._digests[key]

    def code(self) -> str:
        """The whole tree tests run against (tests and docs included); only generated outputs are left out."""
        return self.source()

    def impl(self, task: Task, exclude: Iterable[str] = ()) -> Optional[str]:
        """The task's own implementation: its scope minus test files, test data and test-task areas."""
        if not task.scopes:
            return None
        skip = frozenset(gitinfo.normalize_rel(p) for p in exclude)
        areas, icase, scopes = self.areas, self.icase, task.scopes
        return gitinfo.digest_ids(self.ids()[0], lambda p: p not in skip and matches_any(p, scopes, icase)
                                  and not areas.test_area(p) and not areas.artifact(p))

    def scope_digest(self, task: Task) -> Optional[str]:
        if not task.scopes:
            return None
        scoped = [p for p in self.files() if matches_any(p, task.scopes, self.icase)]
        return gitinfo.files_digest(self.project.work_tree, scoped)[0]

    def task_scope_digest(self, task: Task) -> Optional[str]:
        """All files in the task's scope from this snapshot, including its tests."""
        if not task.scopes:
            return None
        return gitinfo.digest_ids(self.ids()[0], lambda p: matches_any(p, task.scopes, self.icase))


# kept for callers that only need the old name
_Live = Live


def undeclared_changes(project: Project, state: State, before: Dict[str, str], after: Dict[str, str],
                       declared: Iterable[str]) -> List[str]:
    """Untracked files outside code scopes that a command changed without declaring them as
    output. They count as source, so the receipt is stale at once (gt warns how to fix it)."""
    work = project.work_tree
    tracked = set(gitinfo.tracked(work)) if gitinfo.is_repo(work) else set()
    skip = set(declared) | set(state.generated())
    return sorted(p for p, oid in after.items()
                  if before.get(p) != oid and p not in tracked and p not in skip and not gitinfo.ignored(p))


def receipt_facts(project: Project, state: State, task: Optional[Task] = None, exclude: Iterable[str] = (),
                  extra_artifacts: Iterable[str] = (),
                  ids: Optional[Tuple[Dict[str, str], str]] = None) -> Dict[str, Any]:
    """Digests recorded on every receipt: the tree the command ran against (``ids`` taken before it ran)."""
    live = Live(project, state, extra_artifacts, ids)
    exclude = list(exclude)
    facts: Dict[str, Any] = {"source_digest": live.source(exclude), "source_method": live.method,
                             "code_digest": live.code()}
    if task is not None and task.scopes:
        facts["impl_digest"] = live.impl(task, exclude)
        facts["task_scope_digest"] = live.task_scope_digest(task)
    return facts


def scope_files(work_tree: Path, scopes: List[str]) -> List[str]:
    if not scopes:
        return []
    icase = gitinfo.is_repo(work_tree) and gitinfo.ignore_case(work_tree)
    return [p for p in gitinfo.project_files(work_tree) if matches_any(p, scopes, icase)]


def scope_digest(project: Project, task: Task) -> Optional[str]:
    """Digest of the files inside the task's locked scope (None without a scope)."""
    if not task.scopes:
        return None
    scoped = scope_files(project.work_tree, task.scopes)
    return gitinfo.files_digest(project.work_tree, scoped)[0]


def spec_digest(task: Task) -> str:
    """What a review vouches for besides the files: the task's acceptance, validator, dependencies,
    scope and kind. A later change to any of these makes the review stale (R01)."""
    from .util import canonical_json, sha256_text
    return sha256_text(canonical_json(task.spec()))


def review_binding(project: Project, state: State, task: Task) -> Dict[str, Any]:
    scoped = scope_files(project.work_tree, task.scopes)
    digest, _ = gitinfo.files_digest(project.work_tree, scoped)
    artifacts_digest, _ = gitinfo.files_digest(project.work_tree, task.artifacts)
    receipts = [r["id"] for r in state.receipts_of(task.id) if r.get("type") != "diff"]
    return {"graph_digest": (state.plan.get("graph") or {}).get("sha256"),
            "scope_digest": digest if task.scopes else None,
            "scope_files": len(scoped),
            "artifacts_digest": artifacts_digest if task.artifacts else None,
            "spec_digest": spec_digest(task),
            "plan_revision": state.plan.get("revision"),
            "receipts": receipts,
            "tree": project.tree_label()}


def _binding_changed(live: Live, task: Task, binds: Dict[str, Any]) -> bool:
    if binds.get("spec_digest") and binds["spec_digest"] != spec_digest(task):
        return True
    if binds.get("scope_digest") and binds["scope_digest"] != live.scope_digest(task):
        return True
    if binds.get("artifacts_digest"):
        current = gitinfo.files_digest(live.project.work_tree, task.artifacts)[0]
        if binds["artifacts_digest"] != current:
            return True
    return False


def annotate(project: Project, state: State, live: Optional[Live] = None) -> State:
    """Mark accepted tasks whose scope/artifact files changed after the passing review."""
    if state.goal is None or not project.exists():
        return state
    live = live or Live(project, state)
    state.graph_code_digest = live.code()
    state.graph_scope_digests = {task.id: live.task_scope_digest(task) for task in state.active_tasks() if task.scopes}
    no_self = bool(project.config().get("require_independent_review"))
    for task in state.active_tasks():
        task.stale = False
        task.no_self = no_self
        if task.state != "accepted" or not task.reviews:
            continue
        binds = task.reviews[-1].get("binds") or {}
        task.stale = _binding_changed(live, task, binds)
    return state


def stale_reviews(project: Project, state: State) -> List[str]:
    annotate(project, state)
    return [t.id for t in state.active_tasks() if t.stale]


def test_files_changed(project: Project, receipt: Dict[str, Any]) -> bool:
    paths = [entry["path"] for entry in receipt.get("test_files", [])]
    digest, _ = gitinfo.files_digest(project.work_tree, paths)
    return digest != receipt.get("test_digest")


def is_pass(receipt: Dict[str, Any]) -> bool:
    """A passing test receipt produced by a command (a manual note never counts)."""
    if receipt.get("manual"):
        return False
    return (receipt.get("type") == "tdd.green" and receipt.get("outcome") == "green_ok") or \
        (receipt.get("type") == "run" and receipt.get("kind") == "affected" and bool(receipt.get("passed")))


def fresh_pass(live: Live, state: State, task: Task) -> Optional[Dict[str, Any]]:
    """The latest passing Green/affected receipt of ``task`` made on the current code."""
    current = live.code()
    for receipt in reversed(state.receipts_of(task.id)):
        if is_pass(receipt) and receipt.get("code_digest") == current:
            return receipt
    return None


def red_tests(state: State, task: Task) -> List[str]:
    red = state.latest_red(task.id)
    return [f["path"] for f in red.get("test_files", [])] if red else []


def fresh_impl_pass(live: Live, state: State, task: Task) -> Optional[Dict[str, Any]]:
    """The latest passing Green/affected receipt made on the task's current own implementation
    (other tasks' work in progress does not matter here; gt check judges the whole tree)."""
    current = live.impl(task, red_tests(state, task))
    if current is None:
        return fresh_pass(live, state, task)
    for receipt in reversed(state.receipts_of(task.id)):
        if is_pass(receipt) and receipt.get("impl_digest") == current:
            return receipt
    return None


def needs_own_evidence(live: Live, state: State, task: Task) -> bool:
    """A parent whose scope is fully covered by its subtasks relies on their evidence."""
    children = [c for c in state.children(task.id) if c.kind == "code"]  # they need evidence themselves
    if task.tdd or not children or not task.scopes:
        return True
    child_scopes = [s for child in children for s in child.scopes]
    if not child_scopes:
        return True
    # test files and test data belong to test subtasks; every other file needs a code child
    scoped = [p for p in live.files() if matches_any(p, task.scopes, live.icase) and not live.areas.test_area(p)]
    return any(not matches_any(p, child_scopes, live.icase) for p in scoped)


def needs_fresh_pass(project: Project, state: State, task: Task) -> bool:
    live = Live(project, state)
    return task.kind == "code" and needs_own_evidence(live, state, task) and fresh_pass(live, state, task) is None


def scope_patterns(state: State) -> List[str]:
    patterns: List[str] = []
    for task in state.active_tasks():
        patterns.extend(task.scopes)
    patterns.extend(item["pattern"] for item in state.scope_allow)
    patterns.extend(state.red_test_files())  # a test file bound by a Red belongs to its task
    return patterns


def live_diff(project: Project, state: State) -> Dict[str, Any]:
    """Changes since the goal baseline compared with the union of task scopes."""
    work = project.work_tree
    if not gitinfo.is_repo(work):
        return {"available": False, "reason": "not a git repository"}
    icase = gitinfo.ignore_case(work)
    baseline = ((state.goal or {}).get("baseline") or {}).get("head")
    live = Live(project, state)
    artifacts = set(live.areas.generated)
    changed = [(s, p) for s, p in gitinfo.changed_since(work, baseline) if not gitinfo.ignored(p)]
    untracked = gitinfo.untracked(work)
    files = sorted({p for _, p in changed} | set(untracked))
    patterns = scope_patterns(state)
    # Red-bound test files widen the union, but only explicit scopes (or allowances) lock the goal:
    # a direct task without --scope is not "out of scope" everywhere it touches.
    locked = any(t.scopes for t in state.active_tasks()) or bool(state.scope_allow)
    out_of_scope = [p for p in files if locked and p not in artifacts and not matches_any(p, patterns, icase)]
    forbidden = [pattern for task in state.active_tasks() for pattern in (task.forbidden_scope or [])]
    # A positive scope allowance never overrides an explicit forbidden boundary.
    out_of_scope = sorted(set(out_of_scope) | {p for p in files if matches_any(p, forbidden, icase)})
    allowed = [item["pattern"] for item in state.scope_allow]
    unstarted = []
    for path in files:
        if path in out_of_scope or path in artifacts or matches_any(path, allowed, icase):
            continue
        owners = [t for t in state.active_tasks() if matches_any(path, t.scopes, icase)]
        if owners and all(t.state == "pending" for t in owners):
            unstarted.append(path)
    return {
        "available": True,
        "baseline": baseline,
        "head": gitinfo.head(work),
        "changed": [{"status": s, "path": p} for s, p in changed],
        "untracked": untracked,
        "files": len(files),
        "scoped": locked,
        "out_of_scope": out_of_scope,
        "unstarted": unstarted,
        "artifacts": sorted(artifacts & set(files)),
        "hidden": gitinfo.hidden_changes(work),
    }


def axes(live: Live, state: State) -> Dict[str, str]:
    """Runtime/business/release/install axes from receipts; a pass made on other source is stale."""
    from . import completion
    return completion._axes(collect(live.project, state, live=live))


def receipt_axes(project: Project, state: State) -> Dict[str, str]:
    return axes(Live(project, state), state)


def latest_goal_reviews(state: State) -> "OrderedDict[str, Dict[str, Any]]":
    from . import completion
    return completion.latest_goal_reviews(state)


def collect(project: Project, state: State, live: Optional[Live] = None) -> Snapshot:
    """Gather, once, every filesystem fact the completion contract needs. Always judged on the main
    work tree: evidence from a linked worktree counts only after it is merged."""
    worktree_note = None
    if project.work_tree != project.root:
        worktree_note = "完成检查以主工作树为准（当前在工作树 %s）；工作树里的改动合并后才算数" % project.tree_label()
        project = Project(project.root, project.root)
        live = None
    goal = state.goal
    if goal is None:
        return Snapshot(None, "", "", {}, {}, [], [], project.config() if project.exists() else {}, project.tree_label(),
                        worktree_note, [], {}, state)
    live = live or Live(project, state)
    annotate(project, state, live)
    facts: Dict[str, TaskFacts] = {}
    for task in state.active_tasks():
        green = state.latest(task.id, "tdd.green", "green_ok")
        fresh = fresh_pass(live, state, task)
        facts[task.id] = TaskFacts(
            stale=task.stale,
            fresh_pass=fresh["id"] if fresh else None,
            green_test_changed=bool(green and test_files_changed(project, green)),
            needs_own_evidence=needs_own_evidence(live, state, task) if task.kind == "code" else False,
        )
    build = latest_build(state)
    drift = artifact_drift(project, build) if build else []
    return Snapshot(goal, live.source(), live.code(), facts, live_diff(project, state), project.verify(), drift,
                    project.config(), project.tree_label(), worktree_note, sorted(live.areas.generated), {}, state)


def evaluate(project: Project, state: State, release: bool = False, published: bool = False) -> Dict[str, Any]:
    """Completion predicate as a dict (``ok`` is goal_achieved). Collects the snapshot, then judges it
    with completion.evaluate — the same function every other entry point uses."""
    return judge(project, state, release=release, published=published).as_dict()


def release_phase(state: State) -> bool:
    goal = state.goal or {}
    return goal.get("phase") == "release" or bool((goal.get("flags") or {}).get("release"))


def judge(project: Project, state: State, release: bool = False, published: Optional[bool] = None,
          capabilities: Optional[Dict[str, Any]] = None) -> CompletionResult:
    """The shared judgement. A release-phase goal always needs its release gates and the readback
    (``published=None`` means: decided by the goal); only ``gt check --release`` asks the narrower
    pre-publish question with ``published=False``."""
    from . import completion, policy
    snapshot = collect(project, state)
    if snapshot.goal is None:
        return completion.evaluate(snapshot)
    phase = release_phase(state)
    release = release or phase
    published = phase if published is None else published
    gates = policy.gates_of(snapshot.goal, snapshot.config)
    return completion.evaluate(snapshot, gates, capabilities, now_iso(), release=release, published=published)


def artifact_drift(project: Project, receipt: Dict[str, Any]) -> List[str]:
    """Artifacts of a build receipt that no longer exist or no longer have the recorded content."""
    from .util import sha256_file
    out: List[str] = []
    for item in receipt.get("artifacts") or []:
        full = project.work_tree / item.get("path", "")
        if not full.is_file():
            out.append("%s（缺失）" % item.get("path"))
        elif sha256_file(full) != item.get("sha256"):
            out.append("%s（内容已变）" % item.get("path"))
    return out


def asset_set_digest(receipt: Dict[str, Any]) -> str:
    """Identity of a build's exact asset set (paths and content), bound by the readback."""
    from .completion import asset_set_digest as _digest
    return _digest(receipt)


def latest_build(state: State) -> Optional[Dict[str, Any]]:
    builds = [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == "build"
              and r.get("passed") and r.get("artifacts") and r.get("id") not in state.retired]
    return builds[-1] if builds else None


def normalize_scopes(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        scope = normalize_scope(value)
        if scope not in out:
            out.append(scope)
    return out
