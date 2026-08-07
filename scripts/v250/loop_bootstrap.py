"""V2.6 first-round LOOP bootstrap planning and receipt validation."""

from __future__ import annotations

from typing import Any, Mapping


PROJECT_SIZES = {"small", "medium", "large"}
ENVIRONMENT_CHECKER = "goal_release_engineer"
ENVIRONMENT_MODE = "environment_preflight"


class LoopBootstrapError(ValueError):
    """Fail-closed error with a stable V2.6 contract code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LoopBootstrapError("E_V26_LOOP_FACTS", f"{field} must be non-empty")
    return value.strip()


def _logical_version_branch(product_version: str) -> str:
    if not product_version.startswith("V") or len(product_version) < 2:
        raise LoopBootstrapError(
            "E_V26_LOOP_FACTS", "product_version must use V<major.minor>"
        )
    return f"develop-v{product_version[1:].lower()}"


def _namespaced_branch(product_version: str, namespace: str) -> str:
    logical = _logical_version_branch(product_version)
    return f"{namespace}/{logical}" if namespace else logical


def plan_loop_round(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the immutable bootstrap obligations for one LOOP round."""

    round_number = facts.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        raise LoopBootstrapError("E_V26_LOOP_FACTS", "round must be a positive integer")

    plan_preview = facts.get("plan_preview", False)
    if not isinstance(plan_preview, bool):
        raise LoopBootstrapError("E_V26_LOOP_FACTS", "plan_preview must be boolean")
    if plan_preview:
        return {
            "loop_id": _required_text(facts.get("loop_id"), "loop_id"),
            "round": round_number,
            "action": "not_applicable",
            "reason": "plan_preview",
        }

    if round_number > 1:
        receipt_ref = facts.get("bootstrap_receipt_ref")
        if not isinstance(receipt_ref, str) or not receipt_ref.strip():
            raise LoopBootstrapError(
                "E_V26_LOOP_BOOTSTRAP_RECEIPT_REQUIRED",
                "later rounds must reference the first-round bootstrap receipt",
            )
        return {
            "loop_id": _required_text(facts.get("loop_id"), "loop_id"),
            "round": round_number,
            "action": "reuse_bootstrap",
            "bootstrap_receipt_ref": receipt_ref.strip(),
        }

    project_size = facts.get("project_size")
    if project_size not in PROJECT_SIZES:
        raise LoopBootstrapError(
            "E_V26_LOOP_FACTS", "project_size must be small, medium, or large"
        )
    product_version = _required_text(facts.get("product_version"), "product_version")
    source_commit = _required_text(facts.get("source_commit"), "source_commit")
    toolchain_digest = _required_text(
        facts.get("toolchain_digest"), "toolchain_digest"
    )
    dependency_digest = _required_text(
        facts.get("dependency_digest"), "dependency_digest"
    )
    namespace = facts.get("branch_namespace", "codex")
    if not isinstance(namespace, str):
        raise LoopBootstrapError("E_V26_LOOP_FACTS", "branch_namespace must be text")
    namespace = namespace.strip().strip("/")
    user_requested = facts.get("environment_check_requested", False)
    if not isinstance(user_requested, bool):
        raise LoopBootstrapError(
            "E_V26_LOOP_FACTS", "environment_check_requested must be boolean"
        )

    formal_check = project_size in {"medium", "large"} or user_requested
    logical_branch = _logical_version_branch(product_version)
    branch = (
        "not_required"
        if project_size == "small"
        else _namespaced_branch(product_version, namespace)
    )
    worktree = f"develops/v{product_version[1:].lower()}"
    existing = facts.get("existing_environment")
    reuse = False
    reuse_rejected_reasons: list[str] = []
    if existing is not None:
        if not isinstance(existing, Mapping):
            raise LoopBootstrapError(
                "E_V26_LOOP_FACTS", "existing_environment must be an object or null"
            )
        if existing.get("current") is not True:
            reuse_rejected_reasons.append("not_current")
        if existing.get("compatible") is not True:
            reuse_rejected_reasons.append("not_compatible")
        expected_identity = {
            "product_version": product_version,
            "source_commit": source_commit,
            "toolchain_digest": toolchain_digest,
            "dependency_digest": dependency_digest,
        }
        mismatches = [
            field for field, expected in expected_identity.items() if existing.get(field) != expected
        ]
        if mismatches:
            reuse_rejected_reasons.append("identity_mismatch")
            reuse_rejected_reasons.extend(mismatches)
        reuse = not reuse_rejected_reasons

    return {
        "loop_id": _required_text(facts.get("loop_id"), "loop_id"),
        "round": 1,
        "action": "bootstrap",
        "required_order": ["tasklist", "task_assignment", "environment_preflight"],
        "tasklist": "required",
        "task_assignment": "required",
        "environment_preflight": "required",
        "environment_checker": ENVIRONMENT_CHECKER,
        "environment_mode": ENVIRONMENT_MODE,
        "development_environment_check": "required" if formal_check else "not_required",
        "environment_action": "reuse" if reuse else "create",
        "reused_environment": dict(existing) if reuse else None,
        "created_new_environment": not reuse,
        "reuse_rejected_reasons": reuse_rejected_reasons,
        "logical_development_branch": logical_branch,
        "branch_namespace": namespace,
        "development_branch": branch,
        "development_worktree": worktree,
    }


def validate_loop_bootstrap_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate first-round ordering, actor independence, reuse, and branch identity."""

    events = receipt.get("bootstrap_events")
    expected_steps = ["tasklist", "task_assignment", "environment_preflight"]
    if not isinstance(events, list) or len(events) < len(expected_steps):
        raise LoopBootstrapError(
            "E_V26_LOOP_BOOTSTRAP_ORDER",
            "bootstrap_events must prove TaskList, assignment, then environment preflight",
        )
    steps: list[object] = []
    revisions: list[object] = []
    for event in events[: len(expected_steps)]:
        if not isinstance(event, Mapping):
            raise LoopBootstrapError(
                "E_V26_LOOP_BOOTSTRAP_ORDER", "bootstrap event must be an object"
            )
        steps.append(event.get("step"))
        revisions.append(event.get("revision"))
    if steps != expected_steps or any(
        not isinstance(revision, int) or isinstance(revision, bool)
        for revision in revisions
    ) or revisions != sorted(set(revisions)):
        raise LoopBootstrapError(
            "E_V26_LOOP_BOOTSTRAP_ORDER",
            "bootstrap event steps and revisions must be strictly ordered",
        )

    required_flags = (
        ("tasklist_created", "E_V26_LOOP_ROUND_ONE_TASKLIST"),
        ("tasks_assigned", "E_V26_LOOP_ROUND_ONE_ASSIGNMENT"),
        ("environment_checked", "E_V26_LOOP_ROUND_ONE_ENVIRONMENT_CHECK"),
    )
    for field, code in required_flags:
        if receipt.get(field) is not True:
            raise LoopBootstrapError(code, f"{field} must be true")

    if receipt.get("checker_agent_type") != ENVIRONMENT_CHECKER:
        raise LoopBootstrapError(
            "E_V26_ENV_CHECKER_INDEPENDENT",
            "environment preflight must be owned by goal_release_engineer",
        )
    checker_run = _required_text(receipt.get("checker_run_id"), "checker_run_id")
    disallowed_runs = {
        _required_text(receipt.get("lead_run_id"), "lead_run_id"),
        _required_text(
            receipt.get("implementation_owner_run_id"), "implementation_owner_run_id"
        ),
    }
    if checker_run in disallowed_runs:
        raise LoopBootstrapError(
            "E_V26_ENV_CHECKER_INDEPENDENT",
            "environment checker run must differ from Lead and implementation owner",
        )

    project_size = receipt.get("project_size")
    if project_size not in PROJECT_SIZES:
        raise LoopBootstrapError("E_V26_LOOP_FACTS", "invalid project_size")
    product_version = _required_text(receipt.get("product_version"), "product_version")
    namespace = receipt.get("branch_namespace", "codex")
    if not isinstance(namespace, str):
        raise LoopBootstrapError("E_V26_LOOP_FACTS", "branch_namespace must be text")
    namespace = namespace.strip().strip("/")
    if project_size != "small" and receipt.get(
        "development_branch"
    ) != _namespaced_branch(product_version, namespace):
        raise LoopBootstrapError(
            "E_V26_DEVELOPMENT_BRANCH",
            "non-Small environment must bind the exact versioned develop branch",
        )
    if project_size == "small" and receipt.get("development_branch") not in {
        None,
        "not_required",
    }:
        raise LoopBootstrapError(
            "E_V26_DEVELOPMENT_BRANCH",
            "Small may omit the versioned develop branch",
        )

    action = receipt.get("environment_action")
    if receipt.get("compatible_existing_environment") is True and action != "reuse":
        raise LoopBootstrapError(
            "E_V26_EXISTING_ENV_REUSE_REQUIRED",
            "a compatible current environment must be reused",
        )
    if action not in {"reuse", "create"}:
        raise LoopBootstrapError(
            "E_V26_LOOP_FACTS", "environment_action must be reuse or create"
        )

    if action == "reuse":
        reused = receipt.get("reused_environment")
        if not isinstance(reused, Mapping):
            raise LoopBootstrapError(
                "E_V26_EXISTING_ENV_IDENTITY",
                "reuse receipt must include the observed environment identity",
            )
        expected_identity = {
            "product_version": product_version,
            "source_commit": _required_text(
                receipt.get("source_commit"), "source_commit"
            ),
            "toolchain_digest": _required_text(
                receipt.get("toolchain_digest"), "toolchain_digest"
            ),
            "dependency_digest": _required_text(
                receipt.get("dependency_digest"), "dependency_digest"
            ),
        }
        if any(reused.get(field) != value for field, value in expected_identity.items()):
            raise LoopBootstrapError(
                "E_V26_EXISTING_ENV_IDENTITY",
                "reused environment identity must exactly match the receipt baseline",
            )

    return {"ok": True, "environment_action": action}
