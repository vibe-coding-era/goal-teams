"""Host adapters for the LOOP supervisor: how to launch one headless model session and read it back."""

from __future__ import annotations

from typing import Dict, Type

from .base import HostAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .fake import FakeAdapter

ADAPTERS: Dict[str, Type[HostAdapter]] = {"claude": ClaudeAdapter, "codex": CodexAdapter, "fake": FakeAdapter}


def get(name: str, extra_args=()) -> HostAdapter:
    try:
        cls = ADAPTERS[name]
    except KeyError:
        raise ValueError("unknown host %r (one of %s)" % (name, ", ".join(ADAPTERS)))
    return cls(list(extra_args))
