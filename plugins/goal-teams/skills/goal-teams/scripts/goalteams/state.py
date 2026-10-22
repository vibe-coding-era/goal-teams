"""Reducer: rebuild the current goal's state from ledger events (pure, no I/O)."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .models import RED_PAIRABLE, RED_VERIFIED, Criterion, Task
from .util import GTError

__all__ = ["Task", "State", "reduce", "DEFAULT_ROUNDS", "STRUCTURAL_KEYS", "TERMINAL"]

DEFAULT_ROUNDS = {"discussion": 1, "small": 1, "medium": 3, "large": 5, "direct": 1, "tracked": 3}
STRUCTURAL_KEYS = {"deps", "parent", "scopes", "accept", "exit", "validator", "owner", "tdd", "kind", "artifacts",
                   "budget", "requirement_refs", "consumer_refs", "forbidden_scope", "exit_condition"}
TERMINAL = {"accepted", "cancelled"}
# Events the reducer knows; anything else is reported, never silently applied (AC14).
KNOWN_SCHEMAS = ("goal-teams/event@1", "goal-teams/event@2")
KNOWN_EVENTS = {
    "init", "goal", "goal.update", "goal.accept", "goal.finished", "auth.grant",
    "task.add", "task.edit", "task.state", "plan.freeze", "plan.applied",
    "tdd.red", "tdd.green", "tdd.confirm", "run", "run.started", "run.interrupted", "diff", "scope.allow", "review",
    "operation.prepared", "operation.dispatched", "operation.result", "operation.confirmed", "operation.reconciled",
    "control.set", "control.proposal", "control.decision",
    "loop.lease", "loop.lease.end", "loop.reserve", "loop.round", "loop.next",
    "loop.decide", "loop.estimate", "reflect", "context.add", "preflight", "report", "memory", "config",
    "retire", "head.reset", "graph.frozen", "graph.finding", "graph.context",
}


class State:
    def __init__(self) -> None:
        self.init: Optional[Dict[str, Any]] = None
        self.goal: Optional[Dict[str, Any]] = None
        self.goal_history: List[Dict[str, Any]] = []
        self.tasks: "OrderedDict[str, Task]" = OrderedDict()
        self.plan: Dict[str, Any] = {"revision": 0, "applied_revision": 0, "frozen": False, "layers": [],
                                     "critical_path": [], "width": 0, "changes_since_apply": []}
        self.acceptances: List[Dict[str, Any]] = []
        self.unknown_events: List[Dict[str, Any]] = []
        self.running: "OrderedDict[int, Dict[str, Any]]" = OrderedDict()  # run.started without a receipt yet
        self.interrupted_runs: List[Dict[str, Any]] = []
        self.recovery_errors: List[str] = []
        self.operations: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()  # external operations by intent id
        self.control: Dict[str, Any] = {}
        self.proposals: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.lease: Optional[Dict[str, Any]] = None       # the supervisor holding the goal (epoch, pid, status)
        self.lease_history: List[Dict[str, Any]] = []
        self.reservations: List[Dict[str, Any]] = []     # budget reserved before a session/check starts
        self.loop_rounds: List[Dict[str, Any]] = []      # settled supervisor rounds (usage, exit, duration)
        self.loop_next: List[Dict[str, Any]] = []        # deterministic decisions by gt loop next
        self.receipts: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.goal_reviews: List[Dict[str, Any]] = []
        self.round = 1
        self.estimate = 1
        self.estimate_raised: List[int] = []
        self.decisions: List[Dict[str, Any]] = []
        self.auth: List[Dict[str, Any]] = []
        self.scope_allow: List[Dict[str, Any]] = []
        self.context: List[Dict[str, Any]] = []
        self.reflections: List[Dict[str, Any]] = []
        self.preflight: Optional[Dict[str, Any]] = None
        self.reports: List[Dict[str, Any]] = []
        self.graph_charges: List[Dict[str, Any]] = []
        self.graph_errors: List[str] = []
        self.graph_findings: List[Dict[str, Any]] = []
        self.graph_code_digest: Optional[str] = None  # ephemeral live fact, never supplied by a ledger event
        self.graph_scope_digests: Dict[str, str] = {}
        self.retired: Dict[str, Dict[str, Any]] = {}
        self.head_resets: List[Dict[str, Any]] = []
        self.foreign_receipts: List[Dict[str, Any]] = []
        self.round_events: Dict[int, List[Dict[str, Any]]] = {}
        self.last_seq = 0
        self.last_activity_seq = 0

    # ------------------------------------------------------------------ reduce
    def apply(self, event: Dict[str, Any]) -> None:
        kind = event.get("type", "")
        data = event.get("data") or {}
        seq = int(event.get("seq", 0))
        self.last_seq = seq
        event = dict(event)
        event["_round"] = self.round
        if self.goal is not None:
            self.round_events.setdefault(self.round, []).append(event)
        if kind not in ("report", "context.add", "preflight", "reflect", "memory", "config", "run.started"):
            self.last_activity_seq = seq
        schema = event.get("schema")
        if schema is not None and schema not in KNOWN_SCHEMAS:
            self.unknown_events.append({"seq": seq, "type": "%s (%s)" % (kind, schema)})
            return
        handler = getattr(self, "_on_" + kind.replace(".", "_"), None) if kind in KNOWN_EVENTS else None
        if handler is not None:
            handler(event, data, seq)
        elif kind not in KNOWN_EVENTS:
            self.unknown_events.append({"seq": seq, "type": kind})

    def _on_init(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.init = data

    def _on_goal(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        if self.goal is not None:
            closed = dict(self.goal)
            self.goal_history.append(closed)
        goal = dict(data)
        goal.update({"status": "active", "outcome": None, "seq": seq, "ts": event.get("ts")})
        criteria = Criterion.normalize(goal.get("criteria") or goal.get("done") or [])
        goal["criteria"] = [asdict(c) for c in criteria]
        goal["done"] = [c.text for c in criteria]
        goal.setdefault("mode", "direct" if goal.get("size") in ("small", "discussion") else "tracked")
        goal.setdefault("risk", "high" if goal.get("size") == "large" else "normal")
        goal.setdefault("size", "small" if goal["mode"] == "direct" else ("large" if goal["risk"] == "high" else "medium"))
        self._reset_goal_scope()
        self.goal = goal
        self.estimate = int(goal.get("rounds") or DEFAULT_ROUNDS.get(goal.get("size") or "medium", 3))
        self.round_events = {1: [dict(event, _round=1)]}

    def _reset_goal_scope(self) -> None:
        keep_init, keep_history, resets, unknown = self.init, self.goal_history, self.head_resets, self.unknown_events
        last_seq, last_activity = self.last_seq, self.last_activity_seq
        State.__init__(self)
        self.init, self.goal_history, self.head_resets, self.unknown_events = keep_init, keep_history, resets, unknown
        self.last_seq, self.last_activity_seq = last_seq, last_activity

    def _on_goal_update(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        if self.goal is None:
            return
        for item in data.get("add_done", []):
            number = len(self.goal["criteria"]) + 1
            new = Criterion.normalize([item])[0]
            if not isinstance(item, dict) or not item.get("id"):
                new.id = "C%d" % number
            self.goal["criteria"].append(asdict(new))
            self.goal["done"].append(new.text)
        edit = data.get("edit_done")
        if isinstance(edit, dict):
            for index, item in enumerate(self.goal["criteria"]):
                if item["id"] == edit.get("id"):
                    if edit.get("text") is not None:
                        item["text"] = edit["text"]
                        self.goal["done"][index] = edit["text"]
                    if "check" in edit:
                        item["check"] = edit["check"]
        for key in ("size", "flags", "route", "title", "mode", "risk", "domains", "impact", "phase", "gates",
                    "user_requirements"):
            if key in data:
                self.goal[key] = data[key]
        if "size" in data:  # a bigger goal gets at least that size's default number of rounds
            self.estimate = max(self.estimate, DEFAULT_ROUNDS.get(data["size"], self.estimate), self.round)

    def _on_auth_grant(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        grant = dict(data)
        grant.update({"seq": seq, "ts": event.get("ts"), "actor": event.get("actor")})
        self.auth.append(grant)

    def _structural_change(self, reason: str) -> None:
        """Every structural change is a new plan revision; ``frozen`` means the current revision was
        validated as a whole (plan apply). Manual edits are validated too, but one by one."""
        self.plan["revision"] += 1
        self.plan["frozen"] = False
        if self.plan["applied_revision"]:
            self.plan["changes_since_apply"].append(reason)

    def _on_task_add(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        fields = {k: v for k, v in data.items() if k in Task.__dataclass_fields__}
        task = Task(**fields)
        task.created_seq = task.updated_seq = seq
        task.round_added = self.round
        self.tasks[task.id] = task
        self._structural_change("新增 %s" % task.id)

    def _on_task_edit(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        task = self.tasks.get(data.get("id", ""))
        if task is None:
            return
        changes = data.get("changes") or {}
        for key, value in changes.items():
            if key in Task.__dataclass_fields__ and key not in ("id", "state", "reviews"):
                setattr(task, key, value)
        task.updated_seq = seq
        if STRUCTURAL_KEYS.intersection(changes):
            self._structural_change("修改 %s（%s）" % (task.id, "、".join(sorted(STRUCTURAL_KEYS.intersection(changes)))))

    def _on_task_state(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        task = self.tasks.get(data.get("id", ""))
        if task is None:
            return
        target = data.get("to")
        task.updated_seq = seq
        if data.get("note"):
            task.notes.append(data["note"])
        if target == "in_progress":
            task.state = "in_progress"
            task.member = data.get("member") or event.get("actor")
        elif target == "done":
            task.state = "done"
        elif target == "blocked":
            if task.state != "blocked":
                task.prior_state = task.state
            task.state = "blocked"
            task.reason = data.get("reason")
            task.external = bool(data.get("external"))
        elif target == "unblocked":
            task.state = task.prior_state or "pending"
            task.prior_state = None
            task.reason = None
            task.external = False
        elif target == "cancelled":
            task.state = "cancelled"
            task.reason = data.get("reason")
            self._structural_change("取消 %s" % task.id)

    def _on_plan_freeze(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        """Legacy ledgers: a freeze is an apply of the task set as it was."""
        self._mark_applied(data, seq)

    def _on_plan_applied(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        for spec in data.get("tasks") or []:
            fields = {k: v for k, v in spec.items() if k in Task.__dataclass_fields__ and k not in ("state", "reviews")}
            task = self.tasks.get(spec.get("id", ""))
            if task is None:
                task = Task(**fields)
                task.created_seq = seq
                task.round_added = self.round
                self.tasks[task.id] = task
            else:
                for key, value in fields.items():
                    if key != "id":
                        setattr(task, key, value)
            task.updated_seq = seq
        self._mark_applied(data, seq)
        if data.get("graph") is not None:
            self._on_graph_frozen(event, data, seq)

    def _on_graph_frozen(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        from . import graph_contract, graph_budget
        try:
            compiled = graph_contract.compile_state(self)
            if data.get("graph") != compiled:
                raise ValueError("冻结任务图与当前 exact set 不匹配")
            self.plan["graph"] = compiled
            graph_budget.status(self)
        except (GTError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            self.graph_errors.append(str(exc))

    def _on_graph_finding(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.graph_findings.append(dict(data, seq=seq))

    def _on_graph_context(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        pass  # audit record only; it never changes task completion or allocations

    def _mark_applied(self, data: Dict[str, Any], seq: int) -> None:
        """An apply is itself a revision (the whole set was validated); the counter is the reducer's."""
        self.plan.update({
            "revision": self.plan["revision"] + 1,
            "frozen": True,
            "layers": data.get("layers", []),
            "critical_path": data.get("critical_path", []),
            "width": data.get("width", 0),
            "applied_seq": seq,
            "changes_since_apply": [],
        })
        self.plan["applied_revision"] = self.plan["revision"]

    def _on_run_started(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        current = self.goal.get("id") if self.goal else None
        if data.get("goal") is not None and data["goal"] != current:
            return
        if data.get("graph_charge") is not None:
            from . import graph_budget
            graph_budget.observe(self, data["graph_charge"])
        elif self.plan.get("graph") is not None and data.get("task"):
            self.graph_errors.append("任务命令缺少原子预算消费：seq %s" % seq)
        self.running[seq] = dict(data, seq=seq, ts=event.get("ts"), actor=event.get("actor"))

    def _on_run_interrupted(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        from . import run_recovery
        run_recovery.observe(self, event, data, seq)

    def _receipt(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        receipt = dict(data)
        receipt.update({"type": event.get("type"), "seq": seq, "ts": event.get("ts"),
                        "actor": event.get("actor"), "round": self.round})
        started = receipt.get("started")
        if isinstance(started, int):
            self.running.pop(started, None)
        current = self.goal.get("id") if self.goal else None
        if receipt.get("goal") is not None and receipt["goal"] != current:
            self.foreign_receipts.append(receipt)  # started under a goal that was replaced meanwhile
            return
        if receipt.get("late"):
            self.foreign_receipts.append(receipt)  # landed after its task spec changed or the goal closed (AC12)
            return
        self.receipts[receipt["id"]] = receipt

    _on_tdd_red = _receipt
    _on_tdd_green = _receipt
    _on_run = _receipt
    _on_diff = _receipt

    def _on_tdd_confirm(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        receipt = self.receipts.get(data.get("red") or "")
        record = dict(data, seq=seq, ts=event.get("ts"), actor=event.get("actor"))
        if receipt is None:
            return
        receipt.setdefault("confirmations", []).append(record)
        if data.get("matched") and receipt.get("outcome") in RED_PAIRABLE + ("red_expect_mismatch",):
            receipt["outcome"] = RED_VERIFIED
            receipt["confirmed_seq"] = seq

    def _on_goal_accept(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.acceptances.append(dict(data, seq=seq, ts=event.get("ts"), actor=event.get("actor")))

    def _on_goal_finished(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        if self.goal is not None:
            self.goal["status"] = "stopped"
            self.goal["outcome"] = data.get("outcome") or "achieved"
            self.goal["finished"] = dict(data, seq=seq, ts=event.get("ts"))

    def _on_operation_prepared(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        op = dict(data, state="prepared", seq=seq, ts=event.get("ts"), actor=event.get("actor"), history=[])
        self.operations[op["id"]] = op

    def _operation_step(self, data: Dict[str, Any], seq: int, state: Optional[str], kind: str) -> None:
        op = self.operations.get(data.get("id") or "")
        if op is None:
            return
        op["history"].append(dict(data, seq=seq, kind=kind))
        if state is not None:
            op["state"] = state

    def _on_operation_dispatched(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self._operation_step(data, seq, "dispatched", "dispatched")

    def _on_operation_result(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self._operation_step(data, seq, data.get("state") or "unknown", "result")

    def _on_operation_confirmed(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        verdict = data.get("verdict")
        self._operation_step(data, seq, verdict if verdict in ("confirmed", "failed") else "unknown", "confirmed")

    _on_operation_reconciled = _on_operation_confirmed

    def _on_control_set(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.control = dict(data, seq=seq, ts=event.get("ts"), actor=event.get("actor"),
                            revision=(self.control.get("revision") or 0) + 1)

    def _on_control_proposal(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.proposals[data["id"]] = dict(data, state="open", seq=seq, ts=event.get("ts"))

    def _on_control_decision(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        proposal = self.proposals.get(data.get("id") or "")
        if proposal is not None:
            proposal.update(state=data.get("verdict"), decided_seq=seq, decided_by=data.get("by"), decision_note=data.get("note"))

    def _on_loop_lease(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        if self.lease is not None:
            self.lease_history.append(self.lease)
        self.lease = dict(data, status="active", seq=seq, ts=event.get("ts"))

    def _on_loop_lease_end(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        if self.lease is not None and self.lease.get("epoch") == data.get("epoch"):
            self.lease.update(status="ended", outcome=data.get("outcome"), ended_seq=seq)

    def _on_loop_reserve(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.reservations.append(dict(data, seq=seq, ts=event.get("ts"), settled=False))

    def _on_loop_round(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        for item in self.reservations:
            if not item["settled"] and item.get("epoch") == data.get("epoch") and item.get("round") == data.get("round"):
                item["settled"] = True
        self.loop_rounds.append(dict(data, seq=seq, ts=event.get("ts")))

    def _on_loop_next(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.loop_next.append(dict(data, seq=seq, ts=event.get("ts")))
        decision = data.get("decision")
        if decision == "continue":
            self.round += 1
            if self.round > self.estimate:
                self.estimate = self.round
                self.estimate_raised.append(self.round)
        elif data.get("stop") and decision in ("stalled", "blocked", "budget_exhausted", "timed_out", "cancelled", "failed"):
            if self.goal is not None:
                self.goal["status"] = "stopped"
                self.goal["outcome"] = decision

    def _on_retire(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.retired[data.get("id", "")] = dict(data, seq=seq, actor=event.get("actor"))

    def _on_head_reset(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.head_resets.append(dict(data, seq=seq, actor=event.get("actor")))

    def _on_scope_allow(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.scope_allow.append(dict(data, seq=seq))

    def _on_review(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        review = dict(data)
        review.update({"seq": seq, "ts": event.get("ts"), "actor": event.get("actor"), "round": self.round})
        if data.get("task") == "@goal":
            self.goal_reviews.append(review)
            return
        task = self.tasks.get(data.get("task", ""))
        if task is None:
            return
        task.reviews.append(review)
        task.updated_seq = seq
        if data.get("verdict") == "pass":
            if task.state == "done":
                task.state = "accepted"
        else:
            task.notes.append("评审驳回（%s）：%s" % (data.get("by"), data.get("note") or ""))
            if task.state == "blocked":
                task.prior_state = "in_progress"  # unblocking resumes the rework
            elif task.state != "cancelled":
                task.state = "in_progress"

    def _on_loop_decide(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        decision = dict(data)
        decision.update({"round": self.round, "seq": seq, "ts": event.get("ts")})
        self.decisions.append(decision)
        if data.get("decision") == "stop":
            if self.goal is not None:
                self.goal["status"] = "stopped"
                self.goal["outcome"] = data.get("outcome") or "stopped"
        else:
            self.round += 1
            if self.round > self.estimate:
                self.estimate = self.round
                self.estimate_raised.append(self.round)

    def _on_loop_estimate(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.estimate = max(int(data.get("rounds", self.estimate)), self.round)

    def _on_reflect(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.reflections.append(dict(data, seq=seq, ts=event.get("ts"), round=self.round))

    def _on_context_add(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.context.append(dict(data, seq=seq))

    def _on_preflight(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.preflight = dict(data, seq=seq, ts=event.get("ts"))

    def _on_report(self, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
        self.reports.append(dict(data, seq=seq, ts=event.get("ts")))

    # ---------------------------------------------------------------- queries
    def active_tasks(self) -> List[Task]:
        return [t for t in self.tasks.values() if t.active]

    def parents(self) -> List[Task]:
        return [t for t in self.active_tasks() if not t.parent]

    def children(self, task_id: str) -> List[Task]:
        return [t for t in self.active_tasks() if t.parent == task_id]

    def subtasks(self) -> List[Task]:
        return [t for t in self.active_tasks() if t.parent]

    def counts(self) -> Dict[str, int]:
        parents, subs = self.parents(), self.subtasks()
        return {
            "tasks_done": sum(1 for t in parents if self.fully_complete(t)),
            "tasks_total": len(parents),
            "subtasks_done": sum(1 for t in subs if t.complete),
            "subtasks_total": len(subs),
        }

    def fully_complete(self, task: Task) -> bool:
        return task.complete and all(c.complete for c in self.children(task.id))

    def is_ready(self, task: Task) -> bool:
        return task.state == "pending" and all(
            self.tasks[d].complete for d in task.deps if d in self.tasks and self.tasks[d].active)

    def edges(self) -> List[Tuple[str, str]]:
        """``(before, after)``: dependencies first; subtasks before their parent."""
        out = []
        active = {t.id for t in self.active_tasks()}
        for task in self.active_tasks():
            for dep in task.deps:
                if dep in active:
                    out.append((dep, task.id))
            if task.parent and task.parent in active:
                out.append((task.id, task.parent))
        return out

    def dag(self) -> Tuple[List[List[str]], List[str], int, List[str]]:
        """``(layers, critical_path, width, cycle_nodes)`` over active tasks."""
        nodes = [t.id for t in self.active_tasks()]
        incoming: Dict[str, Set[str]] = {n: set() for n in nodes}
        outgoing: Dict[str, Set[str]] = {n: set() for n in nodes}
        for before, after in self.edges():
            incoming[after].add(before)
            outgoing[before].add(after)
        remaining = {n: set(v) for n, v in incoming.items()}
        layers: List[List[str]] = []
        order: List[str] = []
        current = [n for n in nodes if not remaining[n]]
        while current:
            layers.append(current)
            order.extend(current)
            nxt = []
            for node in current:
                for succ in sorted(outgoing[node], key=nodes.index):
                    remaining[succ].discard(node)
                    if not remaining[succ] and succ not in order and succ not in nxt:
                        nxt.append(succ)
            current = sorted(nxt, key=nodes.index)
        cycle = [n for n in nodes if n not in order]
        longest: Dict[str, int] = {}
        prev: Dict[str, Optional[str]] = {}
        for node in order:
            best, best_prev = 1, None
            for before in incoming[node]:
                if before in longest and longest[before] + 1 > best:
                    best, best_prev = longest[before] + 1, before
            longest[node], prev[node] = best, best_prev
        path: List[str] = []
        if longest:
            end = max(order, key=lambda n: (longest[n], -order.index(n)))
            while end is not None:
                path.append(end)
                end = prev[end]
            path.reverse()
        width = max((len(layer) for layer in layers), default=0)
        return layers, path, width, cycle

    def descendants(self, task_id: str) -> List[str]:
        outgoing: Dict[str, Set[str]] = {}
        for before, after in self.edges():
            outgoing.setdefault(before, set()).add(after)
        seen: List[str] = []
        stack = [task_id]
        while stack:
            node = stack.pop()
            for succ in sorted(outgoing.get(node, ())):
                if succ not in seen:
                    seen.append(succ)
                    stack.append(succ)
        return seen

    def parallel_ids(self) -> Set[str]:
        """In-progress tasks with another in-progress task that neither depends on."""
        running = [t.id for t in self.active_tasks() if t.state == "in_progress"]
        reach = {tid: set(self.descendants(tid)) for tid in running}
        out: Set[str] = set()
        for a in running:
            for b in running:
                if a != b and b not in reach[a] and a not in reach[b]:
                    owner_a, owner_b = self.tasks[a].owner, self.tasks[b].owner
                    if owner_a != owner_b or owner_a is None:
                        out.add(a)
        return out

    def receipts_of(self, task_id: Optional[str] = None, types: Iterable[str] = ()) -> List[Dict[str, Any]]:
        wanted = set(types)
        return [r for r in self.receipts.values()
                if (task_id is None or r.get("task") == task_id) and (not wanted or r.get("type") in wanted)]

    def latest(self, task_id: str, receipt_type: str, outcome: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for receipt in reversed(list(self.receipts.values())):
            if receipt.get("task") == task_id and receipt.get("type") == receipt_type:
                if outcome is None or receipt.get("outcome") == outcome:
                    return receipt
        return None

    def _failure_closures(self) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
        """``(open failures, [(failure, closing pass)])`` over run receipts.

        A failed command is closed only by a later pass of the same command for the same
        (task, kind, name); a manual failure by any later pass of that check. The first
        failure stays in the ledger either way.
        """
        pending: "OrderedDict[Tuple[Any, ...], Dict[str, Any]]" = OrderedDict()
        closed: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for receipt in self.receipts.values():
            if receipt.get("type") != "run" or receipt.get("invalid") or receipt.get("id") in self.retired:
                continue
            task = self.tasks.get(receipt.get("task") or "")
            if task is not None and task.state == "cancelled":
                continue
            key = (receipt.get("task"), receipt.get("kind"), receipt.get("name"))
            command = None if receipt.get("manual") else tuple(receipt.get("cmd") or ())
            if not receipt.get("passed"):
                pending[key + (command,)] = receipt
                continue
            for ident in list(pending):
                if ident[:3] != key:
                    continue
                if ident[3] is None or (command is not None and ident[3] == command):
                    closed.append((pending.pop(ident), receipt))
        return list(pending.values()), closed

    def open_failures(self) -> List[Dict[str, Any]]:
        return self._failure_closures()[0]

    def flaky(self) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Same command on the same source failed, then passed: an unstable pass (GT-TEST-FLAKY).
        A pass after the code changed is a fix, not flakiness."""
        return [(f, p) for f, p in self._failure_closures()[1]
                if not f.get("manual") and f.get("source_digest") and f.get("source_digest") == p.get("source_digest")]

    def latest_green(self, task_id: str) -> Optional[Dict[str, Any]]:
        """The latest Green attempt of the task, whatever its outcome."""
        return self.latest(task_id, "tdd.green")

    def red_test_files(self) -> List[str]:
        """Test files bound by valid Reds of active tasks (they belong to the task's scope)."""
        out: List[str] = []
        for receipt in self.receipts.values():
            task = self.tasks.get(receipt.get("task") or "")
            if receipt.get("type") == "tdd.red" and receipt.get("outcome") in RED_PAIRABLE and task and task.active:
                out.extend(f["path"] for f in receipt.get("test_files", []) if f["path"] not in out)
        return out

    def artifact_paths(self) -> List[str]:
        """Build outputs declared with ``gt run --artifact``."""
        out: List[str] = []
        for receipt in self.receipts.values():
            for item in receipt.get("artifacts") or []:
                if item.get("path") and item["path"] not in out:
                    out.append(item["path"])
        return out

    def generated(self) -> Dict[str, str]:
        """``{path: "artifact" | "output"}``: files declared as produced by a recorded command
        (``gt run --artifact`` build outputs, ``--output`` test reports). Never guessed."""
        out: Dict[str, str] = {}
        for receipt in self.receipts.values():
            task = self.tasks.get(receipt.get("task") or "")
            if task is not None and task.state == "cancelled":
                continue
            for item in receipt.get("artifacts") or []:
                if item.get("path"):
                    out[item["path"]] = "artifact"
            for path in receipt.get("outputs") or []:
                if isinstance(path, str):
                    out[path] = "output"
        return out

    def latest_red(self, task_id: str) -> Optional[Dict[str, Any]]:
        """The latest Red that can be paired with a Green (observed or verified)."""
        for receipt in reversed(list(self.receipts.values())):
            if receipt.get("task") == task_id and receipt.get("type") == "tdd.red" \
                    and receipt.get("outcome") in RED_PAIRABLE:
                return receipt
        return None

    def criterion_runs(self, criterion_id: str) -> List[Dict[str, Any]]:
        """Acceptance runs (``gt run - --kind acceptance --name C1``) of one criterion, oldest first."""
        return [r for r in self.receipts.values() if r.get("type") == "run" and r.get("kind") == "acceptance"
                and r.get("name") == criterion_id and not r.get("invalid") and r.get("id") not in self.retired]

    def latest_acceptance(self, criterion_id: str) -> Optional[Dict[str, Any]]:
        """The latest manual acceptance (``gt goal accept``) recorded for one criterion."""
        for item in reversed(self.acceptances):
            if item.get("item") == criterion_id:
                return item
        return None

    def open_red(self, task_id: str) -> Optional[Dict[str, Any]]:
        """The latest valid Red that has no Green after it."""
        red = self.latest_red(task_id)
        green = self.latest(task_id, "tdd.green", "green_ok")
        if red is not None and (green is None or green["seq"] < red["seq"]):
            return red
        return None

    def blocked(self) -> List[Task]:
        return [t for t in self.active_tasks() if t.state == "blocked"]

    def last_decision(self) -> Optional[Dict[str, Any]]:
        return self.decisions[-1] if self.decisions else None

    def evidence_in_round(self, round_number: int) -> int:
        return sum(1 for r in self.receipts.values() if r.get("round") == round_number and r.get("type") != "diff")

    def members(self, round_number: Optional[int] = None) -> List[str]:
        """Members who actually acted (recorded, started or reviewed) in the round."""
        names: List[str] = []

        def add(name: Any) -> None:
            if isinstance(name, str) and name and name != "lead" and name not in names:
                names.append(name)

        if round_number is None:
            events = [e for r in sorted(self.round_events) for e in self.round_events[r]]
        else:
            events = self.round_events.get(round_number, [])
        for event in events:
            data = event.get("data") or {}
            add(event.get("actor"))
            if not isinstance(data, dict):
                continue
            if event.get("type") == "review":
                add(data.get("by"))
            elif event.get("type") == "task.state" and data.get("to") == "in_progress":
                add(data.get("member"))
        for task in self.active_tasks():
            if task.state == "in_progress":
                add(task.member or task.owner)
        return names

    def auth_covers(self, action: str) -> Optional[Dict[str, Any]]:
        for grant in reversed(self.auth):
            if action in grant.get("actions", []):
                return grant
        return None


def reduce(events: Iterable[Dict[str, Any]]) -> State:
    state = State()
    for event in events:
        state.apply(event)
    return state
