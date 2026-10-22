"""The adapter contract and the capability report (every item says how it was established)."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import runner

# Status of one capability item: how we know. "probe_passed" needs a real probe in this session;
# "documented"/"help_observed" are weaker; "unavailable"/"unknown" are honest defaults (INV10).
STATUSES = ("probe_passed", "help_observed", "documented", "failed", "unavailable", "unknown")
# The six items V2.95 probes; everything else is reported as unavailable, never guessed.
PROBED = ("headless_launch", "event_schema", "cancel", "process_containment", "token_usage", "monetary_cost")
FIXED_UNAVAILABLE = ("predispatch_tool_limit", "control_store_protection", "approval_provenance",
                     "external_mediation", "cleanup_observation", "tool_observation")


@dataclass
class LaunchResult:
    exit_code: int
    duration_ms: int
    timed_out: bool
    log: str
    log_sha256: str
    usage: Dict[str, Any] = field(default_factory=dict)   # tokens / cost / turns, or {"status": "unknown"}
    summary: str = ""


def item(status: str, evidence: str) -> Dict[str, str]:
    assert status in STATUSES
    return {"status": status, "evidence": evidence}


class HostAdapter:
    name = "base"
    binary = ""

    def __init__(self, extra_args: Optional[List[str]] = None) -> None:
        self.extra_args = list(extra_args or [])

    # ---- probing ---------------------------------------------------------------------
    def version(self) -> Optional[str]:
        path = shutil.which(self.binary) if self.binary else None
        if not path:
            return None
        try:
            proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        text = (proc.stdout or proc.stderr or "").strip()
        return text.splitlines()[0] if text else None

    def help_text(self, *args: str) -> str:
        path = shutil.which(self.binary) if self.binary else None
        if not path:
            return ""
        try:
            proc = subprocess.run([path, *args, "--help"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (proc.stdout or "") + (proc.stderr or "")

    def probe(self) -> Dict[str, Any]:
        """CapabilityReport: per item status + evidence; fixed items are unavailable in V2.95."""
        report: Dict[str, Any] = {"host": self.name, "version": self.version(), "items": {}}
        version = report["version"]
        available = item("probe_passed", "%s version observed: %s" % (self.binary or self.name, version)) if version \
            else item("unavailable", "%s is missing or its version command did not succeed" % (self.binary or self.name))
        report["items"]["command_available"] = available
        report["items"]["headless_launch"] = item("unknown", "version observed; no headless session was launched by this probe") \
            if version else item("unavailable", available["evidence"])
        report["items"].update(self.probe_items(version))
        # cancel/containment are gt's own mechanisms and claims; stated per platform, never beyond the tests
        report["items"].setdefault("cancel", item("documented", "runner implements process-group termination "
                                                                 "(POSIX killpg / Windows taskkill /T); no cancellation probe ran here"))
        report["items"].setdefault("process_containment", item(
            "unavailable", "no sandbox is verified: descendants that leave the process group are not contained"))
        for name in FIXED_UNAVAILABLE:
            report["items"][name] = item("unavailable", "not provided in V2.95 (cooperative mode)")
        report["mode"] = "cooperative"
        return report

    def probe_items(self, version: Optional[str]) -> Dict[str, Dict[str, str]]:
        return {}

    # ---- running ---------------------------------------------------------------------
    def command(self, prompt: str) -> List[str]:
        raise NotImplementedError

    def stdin_text(self, prompt: str) -> Optional[str]:
        return None

    def launch(self, prompt: str, cwd: Path, log_path: Path, timeout: float, env: Dict[str, str]) -> LaunchResult:
        result = runner.execute(self.command(prompt), cwd, log_path, timeout, env=env, stdin_text=self.stdin_text(prompt))
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return LaunchResult(result["exit_code"], result["duration_ms"], result["timed_out"], str(log_path),
                            result["log_sha256"], self.collect_usage(text), result["summary"])

    def collect_usage(self, log_text: str) -> Dict[str, Any]:
        return {"status": "unknown"}


def json_lines(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out
