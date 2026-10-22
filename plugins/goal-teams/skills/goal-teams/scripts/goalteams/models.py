"""Domain objects shared by the reducer, the live collector and the completion contract.

Everything here is plain data: no I/O, no git, no clock. Digests are always computed by the
tool; a caller never hands in a "trusted" digest or a passing verdict.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Assurance of a review or acceptance, by what actually produced it (never by the role name):
#   self                  the implementer looked at its own work (``--self``)
#   self_reported         the session wrote down a claim about an outside actor ("the user said OK")
#   correlated_reviewer   another member or session of the same model family reviewed it
#   host_verified_actor   the host's own approval record names the actor (not available in V2.95)
#   external_independent  a record from outside the session (not available in V2.95)
ASSURANCE = ("self", "self_reported", "correlated_reviewer", "host_verified_actor", "external_independent")

# States a Red can be in (GT-TEST-RED-STATES): only red_verified counts as valid TDD evidence.
RED_OBSERVED = "red_observed"      # the command failed; the reason is not checked yet
RED_VERIFIED = "red_verified"      # the failure matches the expected behaviour (``--expect`` or ``tdd confirm``)
RED_INVALID = "red_invalid"        # the command never ran, timed out, or was not a test failure
RED_LEGACY_OK = "red_ok"           # legacy receipts: treated as observed (unverified)
RED_PAIRABLE = (RED_OBSERVED, RED_VERIFIED, RED_LEGACY_OK)


@dataclass
class Task:
    id: str
    title: str
    parent: Optional[str] = None
    owner: Optional[str] = None
    validator: Optional[str] = None
    deps: List[str] = field(default_factory=list)
    priority: str = "P1"
    scopes: List[str] = field(default_factory=list)
    accept: Optional[str] = None
    exit: Optional[str] = None
    budget: Any = None
    requirement_refs: Optional[List[str]] = None
    consumer_refs: Optional[List[str]] = None
    forbidden_scope: List[str] = field(default_factory=list)
    exit_condition: Optional[Dict[str, Any]] = None
    tdd: bool = False
    kind: str = "code"
    artifacts: List[str] = field(default_factory=list)
    state: str = "pending"
    prior_state: Optional[str] = None
    reason: Optional[str] = None
    external: bool = False
    member: Optional[str] = None
    created_seq: int = 0
    updated_seq: int = 0
    round_added: int = 1
    reviews: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Set by checks.annotate (needs the filesystem): files changed after the passing review.
    stale: bool = False
    # Set by checks.annotate from project config: a self-review (--self) does not count as acceptance.
    no_self: bool = False

    @property
    def complete(self) -> bool:
        if self.state == "accepted":
            if self.no_self and self.reviews and self.reviews[-1].get("self"):
                return False
            return not self.stale
        return self.state == "done" and not self.validator

    @property
    def active(self) -> bool:
        return self.state != "cancelled"

    def spec(self) -> Dict[str, Any]:
        """The fields a review vouches for besides the files (R01)."""
        return {k: getattr(self, k) for k in SPEC_FIELDS}


SPEC_FIELDS = ("accept", "exit", "validator", "owner", "deps", "scopes", "kind", "tdd", "artifacts", "parent",
               "budget", "requirement_refs", "consumer_refs", "forbidden_scope", "exit_condition")
# Task fields a plan file or ``gt task add`` may set.
TASK_INPUT_FIELDS = ("id", "title", "parent", "owner", "validator", "deps", "priority", "scopes", "accept", "exit",
                     "budget", "tdd", "kind", "artifacts", "requirement_refs", "consumer_refs", "forbidden_scope", "exit_condition")


@dataclass
class Criterion:
    """One observable done criterion of the goal; ``check`` is a command that proves it (argv)."""
    id: str
    text: str
    check: Optional[List[str]] = None

    @classmethod
    def normalize(cls, items: List[Any]) -> List["Criterion"]:
        out: List[Criterion] = []
        for index, item in enumerate(items or [], start=1):
            if isinstance(item, dict):
                out.append(cls(item.get("id") or "C%d" % index, str(item.get("text") or ""), item.get("check") or None))
            else:
                out.append(cls("C%d" % index, str(item), None))
        return out

    def digest_text(self) -> str:
        return self.text


@dataclass
class GateRule:
    """Whether a gate applies to this goal and why; ``kind``: quality, coordination or release."""
    name: str
    kind: str
    required: bool
    reason: str
    min_assurance: Optional[str] = None


@dataclass
class TaskFacts:
    """Filesystem facts about one task, collected once per snapshot (the pure judge never looks at files)."""
    stale: bool = False
    fresh_pass: Optional[str] = None          # id of a passing Green/affected receipt made on the current code
    green_test_changed: bool = False          # test files changed after the latest passing Green
    needs_own_evidence: bool = True


@dataclass
class Snapshot:
    """Everything the completion contract judges: reduced state plus the live facts of one moment."""
    goal: Dict[str, Any]
    source_digest: str
    code_digest: str
    tasks: Dict[str, TaskFacts]
    diff: Dict[str, Any]
    verify_problems: List[str]
    build_drift: List[str]
    config: Dict[str, Any]
    tree_label: str = "."
    worktree_note: Optional[str] = None
    generated: List[str] = field(default_factory=list)
    criteria_runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # latest acceptance run per criterion
    state: Any = None  # the reduced State (queries only; the judge must not mutate it)

    def ref(self) -> str:
        from .util import canonical_json, sha256_text
        # last_activity_seq: run.started, reports and notes do not change what is judged
        return sha256_text(canonical_json({
            "goal": self.goal.get("id"), "seq": getattr(self.state, "last_activity_seq", None), "source": self.source_digest,
            "code": self.code_digest, "tree": self.tree_label, "verify": self.verify_problems,
            "drift": self.build_drift}))[:16]


@dataclass
class CompletionResult:
    """The one answer every entry point shows (gt check, finish, report, loop, goal accept)."""
    status: str                              # achieved | review_required | acceptance_required | blocked | unverified | no_goal
    engineering_passed: bool
    criteria_accepted: bool
    goal_achieved: bool
    reasons: List[str] = field(default_factory=list)
    passes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    axes: Dict[str, str] = field(default_factory=dict)
    gates: Dict[str, str] = field(default_factory=dict)       # gate -> passed | failed | not_run | stale | not_required
    criteria: List[Dict[str, Any]] = field(default_factory=list)
    assurance: Dict[str, Any] = field(default_factory=dict)
    snapshot_ref: str = ""
    diff: Dict[str, Any] = field(default_factory=dict)
    source_digest: str = ""

    @property
    def ok(self) -> bool:
        return self.goal_achieved

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["schema"] = "goal-teams/completion@1"
        return data
