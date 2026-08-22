"""Hash-chained V2.63 TurnReceipt contracts."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from scripts.v250.generation_runtime import (
    canonical_json_digest,
    sha256_bytes,
)


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEGACY_BINDING_FIELDS = (
    "generation_snapshot_sha256",
    "derived_route_sha256",
    "task_exact_set_sha256",
    "locked_scope_sha256",
    "authorization_lineage_sha256",
    "context_sha256",
)
CURRENT_BINDING_FIELDS = LEGACY_BINDING_FIELDS + ("context_delta_sha256",)
AUTHORIZATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "issuer",
        "proof_strength",
        "action_allowlist",
        "target_scope",
        "authorization_lineage_sha256",
        "previous_turn_receipt_sha256",
        "receipt_sha256",
    }
)


class TurnReceiptError(ValueError):
    """Stable fail-closed cross-turn binding error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise TurnReceiptError(code, message)


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("E_V263_TURN_FIELD", f"{field} must be non-empty text")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("E_V263_TURN_DIGEST", f"{field} must be lowercase SHA-256")
    return value


def _bindings(value: Mapping[str, Any]) -> dict[str, str]:
    keys = set(value) if isinstance(value, Mapping) else set()
    if not isinstance(value, Mapping) or (
        keys != set(LEGACY_BINDING_FIELDS)
        and keys != set(CURRENT_BINDING_FIELDS)
    ):
        _fail("E_V263_TURN_BINDINGS", "turn bindings have missing or unknown fields")
    fields = (
        CURRENT_BINDING_FIELDS
        if "context_delta_sha256" in value
        else LEGACY_BINDING_FIELDS
    )
    return {field: _sha(value.get(field), field) for field in fields}


def _action(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "target"}:
        _fail("E_V263_TURN_ACTION", "action requires exact type and target fields")
    return {
        "type": _nonempty(value.get("type"), "action.type"),
        "target": _nonempty(value.get("target"), "action.target"),
    }


def _text_list(value: Sequence[str], field: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail("E_V263_TURN_FIELD", f"{field} must be an array")
    result = list(value)
    if not result or not all(isinstance(item, str) and item.strip() for item in result):
        _fail("E_V263_TURN_FIELD", f"{field} must contain non-empty strings")
    if len(result) != len(set(result)):
        _fail("E_V263_TURN_FIELD", f"{field} contains duplicates")
    return result


def _context_delta_digest(value: Any) -> str:
    if isinstance(value, bytes):
        return sha256_bytes(value)
    if isinstance(value, str):
        return sha256_bytes(value.encode("utf-8"))
    try:
        return canonical_json_digest(value)
    except (TypeError, ValueError) as exc:
        raise TurnReceiptError(
            "E_V263_TURN_CONTEXT_DELTA",
            "context_delta must be bytes, text, or canonical JSON data",
        ) from exc


def _verify_context_delta(
    bindings: Mapping[str, str], context_delta: Any | None
) -> bool:
    expected = bindings.get("context_delta_sha256")
    if expected is None:
        if context_delta is not None:
            _fail(
                "E_V263_TURN_CONTEXT_DELTA",
                "legacy bindings cannot claim a current context delta",
            )
        return False
    if context_delta is None or _context_delta_digest(context_delta) != expected:
        _fail(
            "E_V263_TURN_CONTEXT_DELTA",
            "actual context delta differs from its binding",
        )
    return True


def _receipt_digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "receipt_sha256"}
    return canonical_json_digest(payload)


def _validate_previous(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != (
        "goal-teams-turn-receipt-v2.65"
    ):
        _fail("E_V263_TURN_PREVIOUS", "invalid previous turn receipt")
    claimed = value.get("receipt_sha256")
    if not isinstance(claimed, str) or claimed != _receipt_digest(value):
        _fail("E_V263_TURN_PREVIOUS", "previous turn receipt digest differs")
    if not isinstance(value.get("turn_index"), int) or value["turn_index"] < 1:
        _fail("E_V263_TURN_PREVIOUS", "invalid previous turn index")
    _bindings(value.get("bindings"))
    _action(value.get("action"))
    return dict(value)


def _changed_fields(
    previous_bindings: Mapping[str, str],
    next_bindings: Mapping[str, str],
    previous_action: Mapping[str, str],
    next_action: Mapping[str, str],
) -> list[str]:
    if set(previous_bindings) != set(next_bindings):
        _fail(
            "E_V263_TURN_BINDING_VERSION",
            "binding versions cannot change inside one turn chain",
        )
    changed = [
        f"bindings.{field}"
        for field in previous_bindings
        if previous_bindings[field] != next_bindings[field]
    ]
    changed.extend(
        f"action.{field}"
        for field in ("type", "target")
        if previous_action[field] != next_action[field]
    )
    return sorted(changed)


def _authorization_metadata(
    *,
    authorization_receipt: Mapping[str, Any] | None,
    expected_authorization_receipt_sha256: str | None,
    trusted_issuer_allowlist: Sequence[str] | None,
    previous_turn_receipt_sha256: str,
    authorization_lineage_sha256: str,
    next_action: Mapping[str, str],
) -> dict[str, Any]:
    supplied = (
        authorization_receipt is not None,
        expected_authorization_receipt_sha256 is not None,
        trusted_issuer_allowlist is not None,
    )
    if not any(supplied):
        return {
            "authorization_receipt_sha256": None,
            "authorization_issuer": None,
            "authorization_proof_strength": "unverified",
            "authorization_verified": False,
            "permission_effect": "none",
        }
    if not all(supplied):
        _fail(
            "E_V263_TURN_AUTH_RECEIPT",
            "receipt, trusted digest, and issuer allowlist are jointly required",
        )
    if (
        not isinstance(authorization_receipt, Mapping)
        or set(authorization_receipt) != AUTHORIZATION_RECEIPT_FIELDS
        or authorization_receipt.get("schema_version")
        != "goal-teams-external-authorization-receipt-v2.65"
    ):
        _fail("E_V263_TURN_AUTH_RECEIPT", "invalid external authorization receipt")
    claimed = _sha(
        authorization_receipt.get("receipt_sha256"),
        "authorization_receipt.receipt_sha256",
    )
    expected = _sha(
        expected_authorization_receipt_sha256,
        "expected_authorization_receipt_sha256",
    )
    if claimed != expected or claimed != _receipt_digest(authorization_receipt):
        _fail("E_V263_TURN_AUTH_RECEIPT", "authorization receipt digest differs")
    _nonempty(authorization_receipt.get("issuer"), "authorization.issuer")
    _text_list(trusted_issuer_allowlist, "trusted_issuer_allowlist")
    proof_strength = authorization_receipt.get("proof_strength")
    if proof_strength not in {"externally_issued", "cryptographically_attested"}:
        _fail(
            "E_V263_TURN_AUTH_PROOF",
            "authorization proof strength is not external",
        )
    if (
        authorization_receipt.get("previous_turn_receipt_sha256")
        != previous_turn_receipt_sha256
    ):
        _fail("E_V263_TURN_AUTH_SCOPE", "authorization previous turn differs")
    if (
        authorization_receipt.get("authorization_lineage_sha256")
        != authorization_lineage_sha256
    ):
        _fail("E_V263_TURN_AUTH_LINEAGE", "authorization lineage differs")
    actions = _text_list(
        authorization_receipt.get("action_allowlist"),
        "authorization.action_allowlist",
    )
    targets = _text_list(
        authorization_receipt.get("target_scope"), "authorization.target_scope"
    )
    if next_action["type"] not in actions or next_action["target"] not in targets:
        _fail(
            "E_V263_TURN_AUTH_SCOPE",
            "next action is outside the authorization allowlist or target scope",
        )
    # A repository-owned canonical JSON digest, expected digest, and caller-owned
    # issuer list prove integrity only.  They do not authenticate a host actor.
    # Until a host capability or verifiable signature boundary exists, this
    # evidence must remain non-authorizing.
    return {
        "authorization_receipt_sha256": None,
        "authorization_issuer": None,
        "authorization_proof_strength": "unverified",
        "authorization_verified": False,
        "permission_effect": "none",
    }


def create_authorized_delta(
    *,
    previous_turn_receipt: Mapping[str, Any],
    next_bindings: Mapping[str, Any],
    next_action: Mapping[str, Any],
    decision: str,
    reason: str,
    authorization_lineage_sha256: str,
    authorization_evidence_refs: Sequence[str],
    authorization_receipt: Mapping[str, Any] | None = None,
    expected_authorization_receipt_sha256: str | None = None,
    trusted_issuer_allowlist: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create an exact delta without minting authority.

    Without all external receipt inputs the delta is explicitly unverified and
    has ``permission_effect=none``.  It can be used by offline compatibility
    projections, but the runtime entry rejects it.
    """

    previous = _validate_previous(previous_turn_receipt)
    normalized_bindings = _bindings(next_bindings)
    normalized_action = _action(next_action)
    if decision not in {"continue", "replan", "blocked"}:
        _fail("E_V263_TURN_DECISION", "unknown LOOP decision")
    explanation = _nonempty(reason, "reason")
    lineage = _sha(authorization_lineage_sha256, "authorization_lineage_sha256")
    if lineage != normalized_bindings["authorization_lineage_sha256"]:
        _fail("E_V263_TURN_AUTH_LINEAGE", "delta authorization lineage differs")
    evidence = _text_list(authorization_evidence_refs, "authorization_evidence_refs")
    changed = _changed_fields(
        previous["bindings"],
        normalized_bindings,
        previous["action"],
        normalized_action,
    )
    if not changed:
        _fail("E_V263_TURN_DELTA", "authorized delta has no changed fields")
    authorization = _authorization_metadata(
        authorization_receipt=authorization_receipt,
        expected_authorization_receipt_sha256=expected_authorization_receipt_sha256,
        trusted_issuer_allowlist=trusted_issuer_allowlist,
        previous_turn_receipt_sha256=previous["receipt_sha256"],
        authorization_lineage_sha256=lineage,
        next_action=normalized_action,
    )
    delta: dict[str, Any] = {
        "schema_version": "goal-teams-authorized-turn-delta-v2.65",
        "previous_turn_receipt_sha256": previous["receipt_sha256"],
        "from_bindings_sha256": canonical_json_digest(previous["bindings"]),
        "to_bindings_sha256": canonical_json_digest(normalized_bindings),
        "from_action_sha256": canonical_json_digest(previous["action"]),
        "to_action_sha256": canonical_json_digest(normalized_action),
        "changed_fields": changed,
        "decision": decision,
        "reason": explanation,
        "authorization_lineage_sha256": lineage,
        "authorization_evidence_refs": evidence,
        **authorization,
    }
    delta["receipt_sha256"] = _receipt_digest(delta)
    return delta


def _validate_delta(
    value: Mapping[str, Any],
    *,
    previous: Mapping[str, Any],
    bindings: Mapping[str, str],
    action: Mapping[str, str],
    changed_fields: list[str],
    decision: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != (
        "goal-teams-authorized-turn-delta-v2.65"
    ):
        _fail("E_V263_TURN_DELTA", "invalid authorized delta")
    if value.get("receipt_sha256") != _receipt_digest(value):
        _fail("E_V263_TURN_DELTA_DIGEST", "authorized delta digest differs")
    if value.get("previous_turn_receipt_sha256") != previous["receipt_sha256"]:
        _fail("E_V263_TURN_DELTA_BINDING", "delta previous receipt differs")
    if value.get("from_bindings_sha256") != canonical_json_digest(previous["bindings"]):
        _fail("E_V263_TURN_DELTA_BINDING", "delta source bindings differ")
    if value.get("to_bindings_sha256") != canonical_json_digest(bindings):
        _fail("E_V263_TURN_DELTA_BINDING", "delta target bindings differ")
    if value.get("from_action_sha256") != canonical_json_digest(previous["action"]):
        _fail("E_V263_TURN_DELTA_BINDING", "delta source action differs")
    if value.get("to_action_sha256") != canonical_json_digest(action):
        _fail("E_V263_TURN_DELTA_BINDING", "delta target action differs")
    if value.get("changed_fields") != changed_fields:
        _fail("E_V263_TURN_DELTA_BINDING", "delta changed fields differ")
    if value.get("decision") != decision:
        _fail("E_V263_TURN_DELTA_BINDING", "delta LOOP decision differs")
    if value.get("authorization_lineage_sha256") != bindings[
        "authorization_lineage_sha256"
    ]:
        _fail("E_V263_TURN_AUTH_LINEAGE", "delta authorization lineage differs")
    _text_list(value.get("authorization_evidence_refs"), "authorization_evidence_refs")
    _nonempty(value.get("reason"), "reason")
    verified = value.get("authorization_verified")
    if verified is True:
        _fail(
            "E_V263_TURN_AUTH_PROOF",
            "repository receipts cannot verify or mint external authorization",
        )
    elif verified is False:
        if (
            value.get("authorization_receipt_sha256") is not None
            or value.get("authorization_issuer") is not None
            or value.get("authorization_proof_strength") != "unverified"
            or value.get("permission_effect") != "none"
        ):
            _fail(
                "E_V263_TURN_AUTH_PROOF",
                "unverified delta cannot claim authorization metadata",
            )
        authorization_digest = None
        issuer = None
        proof = "unverified"
    else:
        _fail(
            "E_V263_TURN_AUTH_PROOF",
            "delta must state whether external authorization was verified",
        )
    return {
        "delta_sha256": _sha(
            value.get("receipt_sha256"), "authorized_delta.receipt_sha256"
        ),
        "authorization_receipt_sha256": authorization_digest,
        "authorization_issuer": issuer,
        "authorization_proof_strength": proof,
        "authorization_verified": verified,
    }


def create_turn_receipt(
    *,
    turn_id: str,
    previous_turn_receipt: Mapping[str, Any] | None,
    bindings: Mapping[str, Any],
    action: Mapping[str, Any],
    decision: str,
    evidence_refs: Sequence[str],
    authorized_delta: Mapping[str, Any] | None = None,
    context_delta: Any | None = None,
    require_verified_authorization: bool = False,
) -> dict[str, Any]:
    """Append a turn; legacy calls remain explicitly offline and unverified."""

    identifier = _nonempty(turn_id, "turn_id")
    normalized_bindings = _bindings(bindings)
    normalized_action = _action(action)
    context_delta_verified = _verify_context_delta(
        normalized_bindings, context_delta
    )
    if not isinstance(require_verified_authorization, bool):
        _fail(
            "E_V263_TURN_AUTH_REQUIRED",
            "require_verified_authorization must be boolean",
        )
    if decision not in {"continue", "replan", "blocked", "stop"}:
        _fail("E_V263_TURN_DECISION", "unknown LOOP decision")
    evidence = _text_list(evidence_refs, "evidence_refs")

    previous_digest: str | None = None
    turn_index = 1
    changed: list[str] = []
    delta_digest: str | None = None
    authorization_digest: str | None = None
    authorization_verified = False
    if previous_turn_receipt is None:
        if authorized_delta is not None:
            _fail("E_V263_TURN_UNEXPECTED_DELTA", "genesis turn cannot carry a delta")
    else:
        previous = _validate_previous(previous_turn_receipt)
        previous_digest = previous["receipt_sha256"]
        turn_index = previous["turn_index"] + 1
        changed = _changed_fields(
            previous["bindings"],
            normalized_bindings,
            previous["action"],
            normalized_action,
        )
        if changed and authorized_delta is None:
            _fail(
                "E_V263_TURN_SILENT_DRIFT",
                "changed bindings or action require an authorized delta",
            )
        if not changed and authorized_delta is not None:
            _fail("E_V263_TURN_UNEXPECTED_DELTA", "no drift exists for the delta")
        if changed:
            delta_validation = _validate_delta(
                authorized_delta,
                previous=previous,
                bindings=normalized_bindings,
                action=normalized_action,
                changed_fields=changed,
                decision=decision,
            )
            delta_digest = delta_validation["delta_sha256"]
            authorization_digest = delta_validation[
                "authorization_receipt_sha256"
            ]
            authorization_verified = delta_validation[
                "authorization_verified"
            ]
            if require_verified_authorization and not authorization_verified:
                _fail(
                    "E_V263_TURN_AUTH_REQUIRED",
                    "runtime transition requires verified external authorization",
                )

    if authorization_verified:
        authorization_state = "externally_verified"
    elif changed and authorized_delta is not None:
        authorization_state = "offline_unverified"
    else:
        authorization_state = "not_required"

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-turn-receipt-v2.65",
        "turn_id": identifier,
        "turn_index": turn_index,
        "previous_turn_receipt_sha256": previous_digest,
        "bindings": normalized_bindings,
        "bindings_sha256": canonical_json_digest(normalized_bindings),
        "action": normalized_action,
        "action_sha256": canonical_json_digest(normalized_action),
        "decision": decision,
        "evidence_refs": evidence,
        "changed_fields": changed,
        "authorized_delta_sha256": delta_digest,
        "receipt_mode": (
            "runtime_bound"
            if set(normalized_bindings) == set(CURRENT_BINDING_FIELDS)
            else "offline_legacy"
        ),
        "context_delta_verified": context_delta_verified,
        "authorization_verification_state": authorization_state,
        "authorization_receipt_sha256": authorization_digest,
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    return receipt


def create_runtime_turn_receipt(
    *,
    turn_id: str,
    previous_turn_receipt: Mapping[str, Any] | None,
    bindings: Mapping[str, Any],
    action: Mapping[str, Any],
    decision: str,
    evidence_refs: Sequence[str],
    context_delta: Any,
    authorized_delta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Current runtime entry requiring context bytes and external auth on drift."""

    if not isinstance(bindings, Mapping) or set(bindings) != set(
        CURRENT_BINDING_FIELDS
    ):
        _fail(
            "E_V263_TURN_BINDINGS",
            "runtime turn requires context_delta_sha256",
        )
    receipt = create_turn_receipt(
        turn_id=turn_id,
        previous_turn_receipt=previous_turn_receipt,
        bindings=bindings,
        action=action,
        decision=decision,
        evidence_refs=evidence_refs,
        authorized_delta=authorized_delta,
        context_delta=context_delta,
        require_verified_authorization=True,
    )
    if receipt["receipt_mode"] != "runtime_bound" or not receipt[
        "context_delta_verified"
    ]:
        _fail("E_V263_TURN_CONTEXT_DELTA", "runtime context delta was not verified")
    return receipt


__all__ = [
    "TurnReceiptError",
    "create_authorized_delta",
    "create_runtime_turn_receipt",
    "create_turn_receipt",
]
