"""Claude Code headless sessions: ``claude -p <prompt> --output-format stream-json --verbose``."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import HostAdapter, item, json_lines


class ClaudeAdapter(HostAdapter):
    name = "claude"
    binary = "claude"

    def probe_items(self, version: Optional[str]) -> Dict[str, Dict[str, str]]:
        if not version:
            return {name: item("unavailable", "claude not on PATH") for name in ("event_schema", "token_usage", "monetary_cost")}
        help_text = self.help_text()
        seen = "--output-format" in help_text and "stream-json" in help_text
        return {
            "event_schema": item("help_observed" if seen else "documented",
                                 "--output-format stream-json" + (" in --help" if seen else " (documented; not seen in --help)")),
            "token_usage": item("documented", "the final result message carries usage (input/output tokens) and num_turns"),
            "monetary_cost": item("documented", "the final result message carries total_cost_usd"),
        }

    def command(self, prompt: str) -> List[str]:
        return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", *self.extra_args]

    def collect_usage(self, log_text: str) -> Dict[str, Any]:
        for message in reversed(json_lines(log_text)):
            if message.get("type") == "result":
                usage = message.get("usage") or {}
                return {"status": "reported", "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"), "turns": message.get("num_turns"),
                        "cost_usd": message.get("total_cost_usd"), "duration_api_ms": message.get("duration_api_ms"),
                        "is_error": bool(message.get("is_error"))}
        return {"status": "unknown", "reason": "no result message in the stream"}
