"""Shared deterministic primitives for the V2.65 Graph Engineering modules.

This module deliberately contains no Graph semantics and performs no writes.
Digest-producing callers are expected to supply timestamps explicitly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, TypeVar


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RFC3339_SECONDS_RE = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})Z$"
)


class DuplicateJSONKeyError(ValueError):
    """A JSON object repeated a key and therefore is not canonical input."""


class CanonicalValueError(ValueError):
    """A value cannot participate in a V2.65 canonical contract."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the exact V2.65 canonical JSON representation of *value*."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalValueError("value is not canonical JSON") from exc


def canonical_sha256(value: object) -> str:
    """Hash *value* using :func:`canonical_json_bytes`."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def self_digest(value: Mapping[str, Any], field: str) -> str:
    """Hash a mapping after removing only its named self-digest field."""

    payload = {key: copy.deepcopy(item) for key, item in value.items() if key != field}
    return canonical_sha256(payload)


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_bytes(raw: bytes | bytearray | memoryview) -> Any:
    """Parse UTF-8 JSON while rejecting duplicate keys, NaN and infinity."""

    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise CanonicalValueError("JSON input must be bytes")

    def reject_constant(value: str) -> Any:
        raise CanonicalValueError(f"non-finite JSON number is forbidden: {value}")

    try:
        return json.loads(
            bytes(raw).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalValueError("input is not valid UTF-8 JSON") from exc


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_int(value: object, *, minimum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return minimum is None or value >= minimum


def is_sha256(value: object, *, allow_evidence_prefix: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if SHA256_RE.fullmatch(value):
        return True
    return bool(allow_evidence_prefix and EVIDENCE_SHA256_RE.fullmatch(value))


ErrorFactory = Callable[[str], Exception]
T = TypeVar("T")


def exact_mapping(
    value: object,
    fields: set[str] | frozenset[str],
    *,
    error: ErrorFactory,
    label: str,
) -> dict[str, Any]:
    """Return a deep dict copy after enforcing an exact object field set."""

    if not isinstance(value, Mapping):
        raise error(f"{label} must be an object")
    actual = set(value)
    if actual != set(fields):
        missing = sorted(set(fields) - actual)
        extra = sorted(actual - set(fields))
        raise error(f"{label} fields differ; missing={missing}; extra={extra}")
    return copy.deepcopy(dict(value))


def unique_string_list(
    value: object,
    *,
    error: ErrorFactory,
    label: str,
    non_empty: bool = False,
    sort_output: bool = True,
) -> list[str]:
    """Validate an ID-like string list, reject duplicates, and normalize sets."""

    if not isinstance(value, list) or (non_empty and not value):
        raise error(f"{label} must be {'a non-empty' if non_empty else 'an'} array")
    if not all(is_non_empty_string(item) for item in value):
        raise error(f"{label} must contain only non-empty strings")
    result = list(value)
    if len(result) != len(set(result)):
        raise error(f"{label} repeats an ID")
    return sorted(result) if sort_output else result


def require_utc_timestamp(value: object, *, error: ErrorFactory, label: str) -> str:
    """Validate UTC RFC3339 timestamps at exact second precision."""

    if not isinstance(value, str) or not UTC_RFC3339_SECONDS_RE.fullmatch(value):
        raise error(f"{label} must be UTC RFC3339 at second precision")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise error(f"{label} is not a real UTC timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise error(f"{label} is not canonical UTC RFC3339")
    return value


def timestamp_value(value: str) -> datetime:
    """Convert an already validated canonical UTC timestamp for comparisons."""

    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def is_json_scalar(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)

