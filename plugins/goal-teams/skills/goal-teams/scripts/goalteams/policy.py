"""Which gates a goal must close, derived from risk, domains, impact and phase — never from the mode.

``mode`` (direct | tracked) only decides how the work is presented and coordinated. Two goals with
the same risk, domains, impact and phase get the same quality gates whatever their mode (AC01).
Gates the policy does not require are reported ``not_required`` with a fixed reason instead of
disappearing (INV01).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional

from .models import ASSURANCE, GateRule

MODES = ("direct", "tracked")
RISKS = ("normal", "high")
DOMAINS = ("code", "ui", "desktop", "agent", "api", "data")
IMPACTS = ("behavior_change", "presentation_only", "docs_only", "config_change", "migration")
PHASES = ("development", "release")
ACTIVITIES = ("discussion", "plan", "execution")

# Legacy sizes map onto the orthogonal dimensions (the SKILL text no longer uses them).
LEGACY_SIZES = ("discussion", "small", "medium", "large")

GATE_TEXT = {
    "plan": "任务、依赖、验收标准经 gt plan apply 校验（tracked）",
    "tdd": "行为变更先看到 Red 再拿到 Green（gt tdd red/green；Red 要核对失败原因）",
    "affected": "受影响面检查在最终代码上通过（gt run --kind affected / gt rerun）",
    "scope": "改动都在锁定范围内（gt diff）",
    "review": "评审：按风险要求的保证等级（self / correlated_reviewer）",
    "audit": "完成审计：goal_completion_auditor 或用户对照完成标准（gt review @goal）",
    "acceptance": "完成标准逐项有当前通过的 --check 记录，或有来源的人工验收（gt goal accept）",
    "visual": "受影响状态的视觉或结构核对（gt run --kind e2e --manual --evidence）",
    "e2e": "真实交互 E2E（gt run --kind e2e）；桌面能力要在对应宿主上运行，浏览器证据不替代原生行为",
    "agent_eval": "Agent 能力用评测证明：基线与有 Agent 两组对比（gt run --kind eval）",
    "security": "安全评审或负向测试（goal_security 的 gt review @goal，或 gt run --kind security）",
    "regression": "冻结版本上跑一次全量回归（gt run --kind regression）",
    "build": "对冻结版本只构建一次并记录产物摘要（gt run --kind build --artifact）",
    "readback": "外部写入后回读确认（gt run --kind release）",
}

# Rule files per routing fact (tools/check.py checks SKILL.md against this and keeps the byte budgets).
RULE_FILES: Dict[str, List[str]] = {
    "work": ["rules/work.md"],
    "tracked": ["rules/tracked.md"],
    "ui": ["rules/ui.md"], "agent": ["rules/agent-dev.md"], "release": ["rules/release.md"],
}


def assurance_at_least(actual: Optional[str], required: Optional[str]) -> bool:
    """``actual`` is at least as strong as ``required`` (both from models.ASSURANCE)."""
    if required is None:
        return True
    for value in (actual, required):
        if value not in ASSURANCE:
            raise ValueError("unknown assurance level %r" % (value,))
    return ASSURANCE.index(actual) >= ASSURANCE.index(required)


def normalize_domains(domains: Iterable[str]) -> List[str]:
    out: List[str] = []
    for item in domains or ():
        if item not in DOMAINS:
            raise ValueError("domain must be one of %s" % ", ".join(DOMAINS))
        if item not in out:
            out.append(item)
    return out or ["code"]


def required_gates(mode: str, risk: str, domains: Iterable[str], impact: str, phase: str,
                   user_requirements: Iterable[str] = (), profile: Optional[Dict[str, Any]] = None
                   ) -> "OrderedDict[str, GateRule]":
    """The applicable gate set. ``user_requirements`` are explicit asks (independent_review, audit, e2e);
    ``profile`` is the project config (require_independent_review ...). Projects can only tighten."""
    if mode not in MODES:
        raise ValueError("mode must be one of %s" % ", ".join(MODES))
    if risk not in RISKS:
        raise ValueError("risk must be one of %s" % ", ".join(RISKS))
    if impact not in IMPACTS:
        raise ValueError("impact must be one of %s" % ", ".join(IMPACTS))
    if phase not in PHASES:
        raise ValueError("phase must be one of %s" % ", ".join(PHASES))
    domains = normalize_domains(domains)
    asks = set(user_requirements or ())
    profile = profile or {}
    high = risk == "high"
    release = phase == "release"
    behavior = impact in ("behavior_change", "migration", "config_change")
    gates: "OrderedDict[str, GateRule]" = OrderedDict()

    def gate(name: str, kind: str, required: bool, reason: str, min_assurance: Optional[str] = None) -> None:
        gates[name] = GateRule(name, kind, required, reason, min_assurance)

    gate("plan", "coordination", mode == "tracked",
         "tracked：多任务需要经校验的计划" if mode == "tracked" else "direct：单任务，不需要计划文件")
    if impact in ("behavior_change", "migration"):
        gate("tdd", "quality", True, "行为变更：先 Red 后 Green")
    elif impact == "config_change":
        gate("tdd", "quality", False, "配置变更：用受影响检查证明，不伪造 TDD")
    elif impact == "docs_only":
        gate("tdd", "quality", False, "纯文档：实际读回与引用检查，不伪造 TDD")
    else:
        gate("tdd", "quality", False, "纯文案或样式：视觉/结构核对，不伪造 TDD")
    gate("affected", "quality", impact != "docs_only",
         "受影响面检查" if impact != "docs_only" else "纯文档：没有受影响的测试面")
    # Locking a scope is planning (coordination); an out-of-scope change fails in either mode once a scope exists.
    gate("scope", "coordination", mode == "tracked",
         "tracked：任务要锁定范围" if mode == "tracked" else "direct：没有锁定范围时越界由你核对 gt diff；锁了范围照样检查")
    gate("criteria", "coordination", mode == "tracked",
         "tracked：目标要声明完成标准" if mode == "tracked" else "direct：可以不声明完成标准；声明了就逐项验收")
    independent = high or release or "independent_review" in asks or bool(profile.get("require_independent_review"))
    if independent:
        why = "高风险" if high else "发布" if release else "用户或项目要求独立评审"
        gate("review", "quality", True, "%s：评审人不能是负责人" % why, "correlated_reviewer")
    else:
        gate("review", "quality", True, "normal 风险：有验证人时由验证人评审，否则实现者自验（self）即可", "self")
    gate("audit", "quality", high or "audit" in asks,
         ("高风险" if high else "用户要求") + "：完成审计对照完成标准" if (high or "audit" in asks)
         else "normal 风险：不需要完成审计（高风险或用户要求时需要）", "self_reported")
    gate("acceptance", "quality", True, "完成标准逐项闭合")
    ui = "ui" in domains or "desktop" in domains
    gate("visual", "quality", ui and impact == "presentation_only",
         "纯文案或样式：核对受影响状态" if (ui and impact == "presentation_only") else "不是纯展示变更")
    gate("e2e", "quality", (ui and behavior) or "e2e" in asks,
         ("UI/桌面交互变更：关键路径真实交互" if ui and behavior else "用户要求 E2E") if ((ui and behavior) or "e2e" in asks)
         else ("纯文档/样式不强制 E2E" if ui else "没有 UI 或桌面领域"))
    agent = "agent" in domains
    gate("agent_eval", "quality", agent and behavior,
         "Agent 能力变更：基线与候选配对评测" if (agent and behavior) else
         ("Agent 领域但不是行为变更" if agent else "没有 Agent 领域"))
    gate("security", "quality" if high else "release", high or release,
         ("高风险" if high else "发布") + "：安全评审或负向测试" if (high or release) else "normal 风险开发期不要求")
    for name, text in (("regression", "全量回归"), ("build", "单次构建"), ("readback", "发布回读")):
        gate(name, "release", release, text if release else "开发期不运行发布门")
    return gates


def quality_signature(gates: "OrderedDict[str, GateRule]") -> Dict[str, Any]:
    """The quality gates alone (AC01 compares these across modes)."""
    return {n: (g.required, g.min_assurance) for n, g in gates.items() if g.kind != "coordination"}


def rule_files(mode: str, domains: Iterable[str], phase: str) -> List[str]:
    """Which rule files the Lead reads besides SKILL.md (budgets in tools/check.py)."""
    files = list(RULE_FILES["work"])
    if mode == "tracked":
        files += RULE_FILES["tracked"]
    domains = normalize_domains(domains)
    if "ui" in domains or "desktop" in domains:
        files += RULE_FILES["ui"]
    if "agent" in domains:
        files += RULE_FILES["agent"]
    if phase == "release":
        files += RULE_FILES["release"]
    return files


def team_for(mode: str, risk: str, domains: Iterable[str], phase: str) -> List[str]:
    """Members worth dispatching; nobody is dispatched just because the role exists."""
    if mode != "tracked":
        return []
    team = ["goal_backend|goal_frontend", "goal_unit_test_designer", "goal_reviewer"]
    domains = normalize_domains(domains)
    if "ui" in domains or "desktop" in domains:
        team += ["goal_e2e_test_designer", "goal_e2e_test_runner"]
    if "agent" in domains:
        team.append("goal_agent_product_manager")
    if risk == "high":
        team += ["goal_requirements_analyst", "goal_qa", "goal_completion_auditor"]
    if phase == "release":
        team += ["goal_release_engineer", "goal_security"]
    return team


def from_legacy(size: str, ui: bool = False, release: bool = False, agent: bool = False,
                risk: str = "normal") -> Dict[str, Any]:
    """Map a legacy ``--size`` call onto mode/risk/domains/impact/phase."""
    if size not in LEGACY_SIZES:
        raise ValueError("size must be one of %s" % ", ".join(LEGACY_SIZES))
    domains = ["code"] + (["ui"] if ui else []) + (["agent"] if agent else [])
    return {
        "activity": "discussion" if size == "discussion" else "execution",
        "mode": "direct" if size in ("discussion", "small") else "tracked",
        "risk": "high" if (size == "large" or risk == "high") else "normal",
        "domains": domains,
        "impact": "behavior_change",
        "phase": "release" if release else "development",
    }


def legacy_size(mode: str, risk: str) -> str:
    """The legacy size label projections still show (render, examples)."""
    if mode == "direct":
        return "small"
    return "large" if risk == "high" else "medium"


def describe(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The routing facts recorded on the goal event: gates with reasons, rule files, team."""
    gates = required_gates(spec["mode"], spec["risk"], spec["domains"], spec["impact"], spec["phase"],
                           spec.get("user_requirements") or (), spec.get("profile"))
    return {
        "mode": spec["mode"], "risk": spec["risk"], "domains": normalize_domains(spec["domains"]),
        "impact": spec["impact"], "phase": spec["phase"],
        "gates": {n: {"required": g.required, "reason": g.reason, "min_assurance": g.min_assurance, "kind": g.kind}
                  for n, g in gates.items()},
        "rules": rule_files(spec["mode"], spec["domains"], spec["phase"]),
        "team": team_for(spec["mode"], spec["risk"], spec["domains"], spec["phase"]),
    }


def gates_of(goal: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> "OrderedDict[str, GateRule]":
    """The gate set of a recorded goal, recomputed from its routing facts and the current profile."""
    return required_gates(goal.get("mode") or "tracked", goal.get("risk") or "normal", goal.get("domains") or ["code"],
                          goal.get("impact") or "behavior_change", goal.get("phase") or "development",
                          goal.get("user_requirements") or (), profile)
