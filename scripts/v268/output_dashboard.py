"""Candidate presentation adapter; retain the validated legacy formatters.

Only a proven completed, empty task section gets a completion notice. Counts,
links, active rows, Context and LOOP remain the underlying renderer's output.
"""

import re

from scripts.v267.output_dashboard import serialize_dashboard as _execution_result
from scripts.v268.specification_delivery import render_document_result as _document_result


_EMPTY_TASK_TABLE = (
    "\n\n| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |\n"
    "|---|---|---|---|\n\n"
)
_CONTEXT_HEADING = "**◆ Context / Knowledge / Tools：**"
_COMPLETION_NOTICE = "本轮全部完成；当前无进行中或剩余任务。"


def _completed_section(rendered: str) -> str:
    # Limit adaptation to the task section; do not rewrite later user text.
    heading = re.search(rf"(?m)^{re.escape(_CONTEXT_HEADING)}$", rendered)
    if heading is None:
        raise ValueError("E_V268_OUTPUT_COMPLETION_LAYOUT")
    tasks = rendered[:heading.start()]
    if tasks.count(_EMPTY_TASK_TABLE) != 1:
        raise ValueError("E_V268_OUTPUT_COMPLETION_LAYOUT")
    return tasks.replace(_EMPTY_TASK_TABLE, f"\n\n{_COMPLETION_NOTICE}\n\n", 1) + rendered[heading.start():]


def serialize_dashboard(value, *, loop_decision, repo_root=None) -> str:
    """Validate/read back via V2.67, then adapt only a completed empty view."""
    rendered = _execution_result(value, loop_decision=loop_decision, repo_root=repo_root)
    dashboard, loop = value["dashboard"], value["loop"]
    completed = (
        not dashboard["active_rows"]
        and dashboard["total_tasks"] > 0
        and dashboard["completed_tasks"] == dashboard["total_tasks"]
        and dashboard["completed_subtasks"] == dashboard["total_subtasks"]
        and loop["gap_count"] == 0
        and loop["blocked_count"] == 0
    )
    return _completed_section(rendered) if completed else rendered


def render_document_result(record, repo_root, *, project, current_round,
                           estimated_total_rounds, loop_decision) -> str:
    """Keep the raw document formatter compatible; adapt gateway delivery."""
    rendered = _document_result(
        record, repo_root, project=project, current_round=current_round,
        estimated_total_rounds=estimated_total_rounds, loop_decision=loop_decision,
    )
    # The raw formatter has already validated the record and current bytes.
    completed = (
        record["stage"] == "observed"
        and len(record["reviews"]) == len(record["authorized_paths"])
        and all(review["verdict"] == "passed" for review in record["reviews"])
    )
    return _completed_section(rendered) if completed else rendered
