"""Codex CLI headless sessions: ``codex exec --json [--sandbox ...] <prompt>``."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import HostAdapter, item, json_lines


class CodexAdapter(HostAdapter):
    name = "codex"
    binary = "codex"

    def probe_items(self, version: Optional[str]) -> Dict[str, Dict[str, str]]:
        if not version:
            return {name: item("unavailable", "codex not on PATH") for name in
                    ("event_schema", "token_usage", "monetary_cost", "process_containment")}
        help_text = self.help_text("exec")
        out = {
            "event_schema": item("help_observed" if "--json" in help_text else "documented",
                                 "codex exec --json emits JSONL events" + (" (seen in exec --help)" if "--json" in help_text else "")),
            "token_usage": item("documented", "turn.completed events carry usage; observation only, not a pre-dispatch limit"),
            "monetary_cost": item("unavailable", "codex exec reports no monetary cost"),
        }
        if "--sandbox" in help_text:
            out["process_containment"] = item("help_observed", "exec --sandbox exists; its isolation is not verified here")
        return out

    def command(self, prompt: str) -> List[str]:
        return ["codex", "exec", "--json", *self.extra_args, prompt]

    def collect_usage(self, log_text: str) -> Dict[str, Any]:
        totals: Dict[str, int] = {}
        turns = 0
        for message in json_lines(log_text):
            if message.get("type") == "turn.completed":
                turns += 1
                for key, value in (message.get("usage") or {}).items():
                    if isinstance(value, int):
                        totals[key] = totals.get(key, 0) + value
        if not turns:
            return {"status": "unknown", "reason": "no turn.completed events"}
        return {"status": "reported", "turns": turns, "cost_usd": None, **totals}
