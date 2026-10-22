"""Route table: which rule files the Lead reads and who to staff, per routing fact.

``policy.py`` decides the gates; this module only maps routing facts to rule files and members and
keeps the legacy ``--size`` vocabulary working. tools/check.py verifies that SKILL.md shows the same
rule files and that every route stays inside its context budget.
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import policy

SIZES = policy.LEGACY_SIZES
MODES = policy.MODES

# Rule files by mode (what the Lead reads besides SKILL.md); add-ons by domain or phase.
BASE_RULES: Dict[str, List[str]] = {
    "discussion": [],
    "direct": list(policy.RULE_FILES["work"]),
    "tracked": list(policy.RULE_FILES["work"]) + list(policy.RULE_FILES["tracked"]),
}
BASE_RULES["small"] = BASE_RULES["direct"]
BASE_RULES["medium"] = BASE_RULES["large"] = BASE_RULES["tracked"]
ADDON_RULES = {"ui": policy.RULE_FILES["ui"][0], "agent": policy.RULE_FILES["agent"][0],
               "release": policy.RULE_FILES["release"][0]}

GATE_TEXT = policy.GATE_TEXT

ESCALATION_SIGNALS = [
    "公共 API / 数据结构 / 迁移（--impact migration 或 --risk high）",
    "认证、支付、安全或个人数据（--risk high）",
    "外部写入（push、PR、发布、部署、数据库）：先 gt auth grant",
    "UI 视觉工作（--domain ui）",
    "用户要求计划、团队分工、并行、跨轮跟踪或发布（--mode tracked）",
]


def describe(mode: str, risk: str = "normal", domains: List[str] = (), impact: str = "behavior_change",
             phase: str = "development", user_requirements: List[str] = (),
             profile: Dict[str, Any] = None) -> Dict[str, Any]:
    """Routing facts for a goal: gates (with reasons), rule files, team."""
    spec = {"mode": mode, "risk": risk, "domains": list(domains) or ["code"], "impact": impact, "phase": phase,
            "user_requirements": list(user_requirements), "profile": profile}
    facts = policy.describe(spec)
    facts["size"] = policy.legacy_size(mode, risk)
    facts["flags"] = {"ui": "ui" in facts["domains"] or "desktop" in facts["domains"], "release": phase == "release",
                      "agent": "agent" in facts["domains"], "risk": risk}
    facts["needs_state"] = mode == "tracked"
    facts["user_requirements"] = list(user_requirements)
    return facts


def derive(size: str, ui: bool = False, release: bool = False, agent: bool = False,
           risk: str = "normal") -> Dict[str, Any]:
    """Legacy compatibility: a ``--size`` call expressed in the new dimensions."""
    if size not in SIZES:
        raise ValueError("size must be one of %s" % ", ".join(SIZES))
    legacy = policy.from_legacy(size, ui=ui, release=release, agent=agent, risk=risk)
    reasons: List[str] = []
    if size == "small" and (risk == "high" or release):
        reasons.append("small：%s，门禁按 %s 要求（mode 仍是 direct）" % (
            "高风险" if risk == "high" else "发布/外部写入", "高风险" if risk == "high" else "发布"))
    if size == "discussion" and (release or ui or agent):
        reasons.append("discussion 只给方案；若要执行，请重新判定")
    facts = describe(legacy["mode"], legacy["risk"], legacy["domains"], legacy["impact"], legacy["phase"])
    facts["requested_size"] = size
    facts["escalations"] = reasons
    facts["gates_list"] = [n for n, g in facts["gates"].items() if g["required"]]
    if size == "discussion":
        facts.update({"size": "discussion", "rules": [], "team": [], "gates_list": []})
    return facts
