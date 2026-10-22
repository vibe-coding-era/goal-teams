"""A scripted host for tests: ``GT_FAKE_HOST`` names a Python script that plays the model session.

The script runs in the project directory with the prompt in ``GT_FAKE_PROMPT_FILE``; it may print a
line ``GT_FAKE_USAGE {"input_tokens": 10, "cost_usd": 0.01}`` to report usage. Never used outside tests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

from .base import HostAdapter, item


class FakeAdapter(HostAdapter):
    name = "fake"
    binary = ""

    def version(self) -> Optional[str]:
        script = os.environ.get("GT_FAKE_HOST")
        return "fake %s" % os.path.basename(script) if script and os.path.isfile(script) else None

    def probe_items(self, version: Optional[str]) -> Dict[str, Dict[str, str]]:
        return {"event_schema": item("documented", "GT_FAKE_USAGE line"),
                "token_usage": item("documented", "GT_FAKE_USAGE line"), "monetary_cost": item("documented", "GT_FAKE_USAGE line")}

    def command(self, prompt: str) -> List[str]:
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", prefix="gt-prompt-", delete=False, encoding="utf-8")
        handle.write(prompt)
        handle.close()
        os.environ["GT_FAKE_PROMPT_FILE"] = handle.name
        return [sys.executable, os.environ.get("GT_FAKE_HOST", ""), handle.name, *self.extra_args]

    def collect_usage(self, log_text: str) -> Dict[str, Any]:
        for line in log_text.splitlines():
            if line.startswith("GT_FAKE_USAGE "):
                try:
                    return dict(json.loads(line[len("GT_FAKE_USAGE "):]), status="reported")
                except ValueError:
                    break
        return {"status": "unknown"}
