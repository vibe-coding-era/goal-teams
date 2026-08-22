"""Fail-closed discovery for one active Goal Teams Skill root.

The module observes candidate roots supplied by a host adapter.  It does not
scan arbitrary home directories, consult environment variables, or fall back
after an invalid candidate.  Every candidate is bound to an expected
activation digest supplied by the caller's trusted discovery boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scripts.v250.generation_runtime import (
    ACTIVE_PATH,
    canonical_json_digest,
    resolve_repo_file,
    sha256_bytes,
)


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
ROOT_KINDS = frozenset(
    {"workspace", "canonical_install", "mirror", "backup", "replay"}
)


class DiscoveryPolicyError(RuntimeError):
    """Stable fail-closed discovery error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DiscoveryCandidateSpec:
    root: Path | str
    root_kind: str
    expected_activation_sha256: str
    discovery_order: int
    source_commit: str | None = None
    source_tree: str | None = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    root_realpath: str
    root_kind: str
    discovery_order: int
    discovery_name: str
    generation_id: str
    product_version: str
    source_commit: str | None
    source_tree: str | None
    skill_sha256: str
    active_sha256: str
    activation_sha256: str
    prompt_manifest_sha256: str
    identity_sha256: str


_DISCOVERY_DECISION_ISSUER = object()


def _candidate_payload(candidate: "DiscoveryCandidate") -> dict[str, object]:
    return {
        "root_realpath": candidate.root_realpath,
        "root_kind": candidate.root_kind,
        "discovery_order": candidate.discovery_order,
        "discovery_name": candidate.discovery_name,
        "generation_id": candidate.generation_id,
        "product_version": candidate.product_version,
        "source_commit": candidate.source_commit,
        "source_tree": candidate.source_tree,
        "skill_sha256": candidate.skill_sha256,
        "active_sha256": candidate.active_sha256,
        "activation_sha256": candidate.activation_sha256,
        "prompt_manifest_sha256": candidate.prompt_manifest_sha256,
        "identity_sha256": candidate.identity_sha256,
    }


def _decision_payload(
    selected: "DiscoveryCandidate",
    candidates: tuple["DiscoveryCandidate", ...],
    selection_rule: str,
) -> dict[str, object]:
    return {
        "schema_version": "goal-teams-discovery-decision-v2.65",
        "selected_identity_sha256": selected.identity_sha256,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "selection_rule": selection_rule,
    }


@dataclass(frozen=True, init=False)
class DiscoveryDecision:
    selected: DiscoveryCandidate
    candidates: tuple[DiscoveryCandidate, ...]
    selection_rule: str
    decision_sha256: str
    _issuer: object = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        selected: DiscoveryCandidate,
        candidates: tuple[DiscoveryCandidate, ...],
        selection_rule: str,
        _issuer: object | None = None,
    ) -> None:
        if _issuer is not _DISCOVERY_DECISION_ISSUER:
            raise DiscoveryPolicyError(
                "E_DISCOVERY_DECISION_PROVENANCE",
                "discovery decisions can only be created by discover_and_select",
            )
        payload = _decision_payload(selected, candidates, selection_rule)
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "selection_rule", selection_rule)
        object.__setattr__(self, "decision_sha256", canonical_json_digest(payload))
        object.__setattr__(self, "_issuer", _issuer)


def validate_discovery_decision(decision: DiscoveryDecision) -> DiscoveryDecision:
    """Reject caller-authored decisions and revalidate the exact decision bytes."""

    if (
        not isinstance(decision, DiscoveryDecision)
        or getattr(decision, "_issuer", None) is not _DISCOVERY_DECISION_ISSUER
    ):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_DECISION_PROVENANCE",
            "runtime requires a discovery-policy-issued decision",
        )
    if (
        not decision.candidates
        or decision.candidates.count(decision.selected) != 1
        or decision.decision_sha256
        != canonical_json_digest(
            _decision_payload(
                decision.selected, decision.candidates, decision.selection_rule
            )
        )
    ):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_DECISION_INVALID", "discovery decision binding differs"
        )
    return decision


def _read_json(root: Path, relative_path: str) -> tuple[dict, bytes]:
    path = resolve_repo_file(root, relative_path)
    raw = path.read_bytes()
    try:
        import json

        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_JSON_INVALID", f"invalid JSON: {relative_path}"
        ) from exc
    if not isinstance(value, dict):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_JSON_INVALID", f"JSON root is not an object: {relative_path}"
        )
    return value, raw


def _skill_name(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_SKILL_INVALID", "SKILL.md is not UTF-8"
        ) from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise DiscoveryPolicyError(
            "E_DISCOVERY_SKILL_INVALID", "SKILL.md frontmatter is missing"
        )
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("name:"):
            name = line.partition(":")[2].strip()
            if name:
                return name
    raise DiscoveryPolicyError(
        "E_DISCOVERY_SKILL_INVALID", "SKILL.md name is missing"
    )


def _validate_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_DIGEST_FORMAT", f"{field} must be lowercase SHA-256"
        )
    return value


def _validate_git_object(value: str | None, field: str) -> str | None:
    if value is not None and (
        not isinstance(value, str) or GIT_OBJECT_RE.fullmatch(value) is None
    ):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_IDENTITY_INVALID", f"{field} must be a 40-hex object id"
        )
    return value


def load_discovery_candidate(spec: DiscoveryCandidateSpec) -> DiscoveryCandidate:
    """Load one candidate with an explicit expected activation digest."""

    if spec.root_kind not in ROOT_KINDS:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ROOT_KIND", f"unknown root kind: {spec.root_kind!r}"
        )
    if not isinstance(spec.discovery_order, int) or spec.discovery_order < 0:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ORDER", "discovery_order must be a non-negative integer"
        )
    expected = _validate_digest(
        spec.expected_activation_sha256, "expected_activation_sha256"
    )
    root = Path(spec.root).resolve()
    skill_path = resolve_repo_file(root, "SKILL.md")
    skill_raw = skill_path.read_bytes()
    active, active_raw = _read_json(root, ACTIVE_PATH)

    active_digest = _validate_digest(
        active.get("activation_manifest_sha256"),
        "ACTIVE activation_manifest_sha256",
    )
    if active_digest != expected:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ACTIVATION_DIGEST_MISMATCH",
            f"trusted expected {expected}, ACTIVE declared {active_digest}",
        )
    activation_path = active.get("activation_manifest")
    if not isinstance(activation_path, str):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ACTIVE_INVALID", "ACTIVE activation_manifest is missing"
        )
    activation, activation_raw = _read_json(root, activation_path)
    actual_activation = sha256_bytes(activation_raw)
    if actual_activation != expected:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ACTIVATION_DIGEST_MISMATCH",
            f"trusted expected {expected}, observed {actual_activation}",
        )

    generation_id = active.get("generation_id")
    if not isinstance(generation_id, str) or activation.get("generation_id") != generation_id:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_GENERATION_MISMATCH",
            "ACTIVE and activation generation differ",
        )
    prompt_path = activation.get("prompt_manifest_path")
    if not isinstance(prompt_path, str):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_PROMPT_INVALID", "activation prompt_manifest_path is missing"
        )
    _prompt, prompt_raw = _read_json(root, prompt_path)
    prompt_digest = sha256_bytes(prompt_raw)
    declared_prompt_digest = _validate_digest(
        activation.get("prompt_plan_digest"), "activation prompt_plan_digest"
    )
    if prompt_digest != declared_prompt_digest:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_PROMPT_DIGEST_MISMATCH",
            f"expected {declared_prompt_digest}, observed {prompt_digest}",
        )

    identity = activation.get("identity")
    if not isinstance(identity, dict):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_IDENTITY_INVALID", "activation identity is missing"
        )
    product_version = identity.get("loaded_runtime_product_version")
    if not isinstance(product_version, str):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_IDENTITY_INVALID", "loaded runtime product version is missing"
        )
    source_commit = _validate_git_object(spec.source_commit, "source_commit")
    source_tree = _validate_git_object(spec.source_tree, "source_tree")
    name = _skill_name(skill_raw)
    identity_payload = {
        "root_realpath": root.as_posix(),
        "root_kind": spec.root_kind,
        "discovery_name": name,
        "generation_id": generation_id,
        "product_version": product_version,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "skill_sha256": sha256_bytes(skill_raw),
        "active_sha256": sha256_bytes(active_raw),
        "activation_sha256": actual_activation,
        "prompt_manifest_sha256": prompt_digest,
    }
    return DiscoveryCandidate(
        discovery_order=spec.discovery_order,
        identity_sha256=canonical_json_digest(identity_payload),
        **identity_payload,
    )


def discover_and_select(
    specs: Iterable[DiscoveryCandidateSpec],
    *,
    expected_name: str = "goal-teams",
    explicit_root: Path | str | None = None,
    expected_identity_sha256: str | None = None,
) -> DiscoveryDecision:
    """Observe all candidates and select exactly one without fallback."""

    ordered_specs = tuple(sorted(specs, key=lambda item: item.discovery_order))
    if len({spec.discovery_order for spec in ordered_specs}) != len(ordered_specs):
        raise DiscoveryPolicyError(
            "E_DISCOVERY_ORDER_COLLISION", "discovery_order values must be unique"
        )
    # Loading is intentionally all-or-nothing.  An invalid earlier candidate is
    # surfaced instead of being skipped in favor of a later valid installation.
    observed = tuple(load_discovery_candidate(spec) for spec in ordered_specs)
    named = tuple(item for item in observed if item.discovery_name == expected_name)
    if not named:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_NO_CANDIDATE", f"no candidate named {expected_name!r}"
        )
    if len(named) != 1:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_MULTIPLE_ACTIVE",
            "multiple active candidates share the discovery name: "
            + ", ".join(item.root_realpath for item in named),
        )

    selected = named[0]
    if selected.root_kind in {"backup", "replay", "mirror"}:
        raise DiscoveryPolicyError(
            "E_DISCOVERY_NO_SELECTABLE_CANDIDATE",
            f"{selected.root_kind} roots cannot be selected as Current",
        )
    if explicit_root is not None:
        expected_root = Path(explicit_root).resolve().as_posix()
        if selected.root_realpath != expected_root:
            raise DiscoveryPolicyError(
                "E_DISCOVERY_EXPLICIT_ROOT_MISMATCH",
                f"explicit root {expected_root} was not the unique candidate",
            )
        rule = "explicit_qualified_root"
    elif selected.root_kind == "workspace":
        expected_identity = _validate_digest(
            expected_identity_sha256, "expected_identity_sha256"
        ) if expected_identity_sha256 is not None else None
        if expected_identity is None or selected.identity_sha256 != expected_identity:
            raise DiscoveryPolicyError(
                "E_DISCOVERY_WORKSPACE_IDENTITY_MISMATCH",
                "workspace selection requires an exact expected identity",
            )
        rule = "identity_matched_workspace"
    elif selected.root_kind == "canonical_install":
        rule = "canonical_install"
    else:  # guarded above; kept explicit for future root-kind additions
        raise DiscoveryPolicyError(
            "E_DISCOVERY_NO_SELECTABLE_CANDIDATE", "no selection rule matched"
        )
    return DiscoveryDecision(
        selected=selected,
        candidates=named,
        selection_rule=rule,
        _issuer=_DISCOVERY_DECISION_ISSUER,
    )


__all__ = [
    "DiscoveryCandidate",
    "DiscoveryCandidateSpec",
    "DiscoveryDecision",
    "DiscoveryPolicyError",
    "discover_and_select",
    "load_discovery_candidate",
    "validate_discovery_decision",
]
