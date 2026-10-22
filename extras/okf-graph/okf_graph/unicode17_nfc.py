"""Host-independent Unicode 17.0.0 NFC normalization.

The runtime uses generated, project-pinned UCD tables and implements canonical
decomposition, canonical ordering, canonical composition, and algorithmic
Hangul normalization without consulting the host Python ``unicodedata`` data.
"""

from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
from typing import Any

from .unicode17_data import (
    ASSIGNED_SCALAR_RANGES as _ASSIGNED_SCALAR_RANGES,
    CANONICAL_COMBINING_CLASS as _CANONICAL_COMBINING_CLASS,
    CANONICAL_DECOMPOSITION as _CANONICAL_DECOMPOSITION,
    COMPOSITION_MAP as _COMPOSITION_MAP,
    SOURCE_DIGESTS as _SOURCE_DIGESTS,
    TABLE_DIGEST,
    UNICODE_VERSION,
)


SOURCE_DIGESTS = dict(_SOURCE_DIGESTS)

_S_BASE = 0xAC00
_L_BASE = 0x1100
_V_BASE = 0x1161
_T_BASE = 0x11A7
_L_COUNT = 19
_V_COUNT = 21
_T_COUNT = 28
_N_COUNT = _V_COUNT * _T_COUNT
_S_COUNT = _L_COUNT * _N_COUNT

_ASSIGNED_RANGE_STARTS = tuple(first for first, _ in _ASSIGNED_SCALAR_RANGES)


class Unicode17Error(ValueError):
    """A stable Unicode 17 input error with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _canonical_table_payload() -> dict[str, Any]:
    return {
        "unicode_version": UNICODE_VERSION,
        "source_digests": dict(sorted(SOURCE_DIGESTS.items())),
        "assigned_scalar_ranges": [
            [first, last] for first, last in _ASSIGNED_SCALAR_RANGES
        ],
        "canonical_combining_class": [
            [codepoint, value]
            for codepoint, value in sorted(_CANONICAL_COMBINING_CLASS.items())
        ],
        "canonical_decomposition": [
            [codepoint, list(value)]
            for codepoint, value in sorted(_CANONICAL_DECOMPOSITION.items())
        ],
        "composition_map": [
            [first, second, composite]
            for (first, second), composite in sorted(_COMPOSITION_MAP.items())
        ],
    }


def _verify_generated_tables() -> None:
    counts = (
        len(_ASSIGNED_SCALAR_RANGES),
        len(_CANONICAL_COMBINING_CLASS),
        len(_CANONICAL_DECOMPOSITION),
        len(_COMPOSITION_MAP),
    )
    if counts != (735, 968, 2_081, 961):
        raise RuntimeError(f"Unicode 17 generated table count mismatch: {counts}")
    canonical = json.dumps(
        _canonical_table_payload(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != TABLE_DIGEST:
        raise RuntimeError(
            f"Unicode 17 generated table digest mismatch: {actual} != {TABLE_DIGEST}"
        )


_verify_generated_tables()


def _is_scalar(codepoint: int) -> bool:
    return 0 <= codepoint <= 0x10FFFF and not 0xD800 <= codepoint <= 0xDFFF


def is_assigned17(codepoint: int) -> bool:
    """Return whether *codepoint* is an assigned Unicode 17 scalar value."""

    if (
        not isinstance(codepoint, int)
        or isinstance(codepoint, bool)
        or not _is_scalar(codepoint)
    ):
        return False
    index = bisect_right(_ASSIGNED_RANGE_STARTS, codepoint) - 1
    if index < 0:
        return False
    first, last = _ASSIGNED_SCALAR_RANGES[index]
    return first <= codepoint <= last


def _hangul_decomposition(codepoint: int) -> tuple[int, ...] | None:
    syllable_index = codepoint - _S_BASE
    if not 0 <= syllable_index < _S_COUNT:
        return None
    leading = _L_BASE + syllable_index // _N_COUNT
    vowel = _V_BASE + (syllable_index % _N_COUNT) // _T_COUNT
    trailing_index = syllable_index % _T_COUNT
    if trailing_index:
        return leading, vowel, _T_BASE + trailing_index
    return leading, vowel


@lru_cache(maxsize=None)
def _decompose_codepoint(codepoint: int) -> tuple[int, ...]:
    hangul = _hangul_decomposition(codepoint)
    if hangul is not None:
        return hangul
    mapping = _CANONICAL_DECOMPOSITION.get(codepoint)
    if mapping is None:
        return (codepoint,)
    result: list[int] = []
    for mapped in mapping:
        result.extend(_decompose_codepoint(mapped))
    return tuple(result)


def _canonical_order(codepoints: list[int]) -> list[int]:
    ordered: list[int] = []
    for codepoint in codepoints:
        combining_class = _CANONICAL_COMBINING_CLASS.get(codepoint, 0)
        insertion = len(ordered)
        if combining_class:
            while insertion:
                previous_class = _CANONICAL_COMBINING_CLASS.get(
                    ordered[insertion - 1], 0
                )
                if previous_class == 0 or previous_class <= combining_class:
                    break
                insertion -= 1
        ordered.insert(insertion, codepoint)
    return ordered


def _hangul_composition(first: int, second: int) -> int | None:
    leading_index = first - _L_BASE
    if 0 <= leading_index < _L_COUNT:
        vowel_index = second - _V_BASE
        if 0 <= vowel_index < _V_COUNT:
            return _S_BASE + (leading_index * _V_COUNT + vowel_index) * _T_COUNT

    syllable_index = first - _S_BASE
    trailing_index = second - _T_BASE
    if (
        0 <= syllable_index < _S_COUNT
        and syllable_index % _T_COUNT == 0
        and 0 < trailing_index < _T_COUNT
    ):
        return first + trailing_index
    return None


def _compose_pair(first: int, second: int) -> int | None:
    hangul = _hangul_composition(first, second)
    if hangul is not None:
        return hangul
    return _COMPOSITION_MAP.get((first, second))


def _canonical_compose(codepoints: list[int]) -> list[int]:
    composed: list[int] = []
    starter: int | None = None
    starter_position = -1
    last_combining_class = 0

    for codepoint in codepoints:
        combining_class = _CANONICAL_COMBINING_CLASS.get(codepoint, 0)
        if starter is not None:
            composite = _compose_pair(starter, codepoint)
            if composite is not None and (
                last_combining_class < combining_class
                or last_combining_class == 0
            ):
                composed[starter_position] = composite
                starter = composite
                continue

        if combining_class == 0:
            starter = codepoint
            starter_position = len(composed)
        composed.append(codepoint)
        last_combining_class = combining_class

    return composed


def normalize_nfc17(value: str) -> str:
    """Return Unicode 17 NFC for *value*, independent of the host UCD version."""

    if not isinstance(value, str):
        raise Unicode17Error(
            "E_UNICODE17_TYPE",
            f"normalize_nfc17 requires str, got {type(value).__name__}",
        )

    decomposed: list[int] = []
    for index, character in enumerate(value):
        codepoint = ord(character)
        if not _is_scalar(codepoint):
            raise Unicode17Error(
                "E_UNICODE17_NON_SCALAR",
                f"non-scalar code point U+{codepoint:04X} at index {index}",
            )
        decomposed.extend(_decompose_codepoint(codepoint))

    if not decomposed:
        return ""
    ordered = _canonical_order(decomposed)
    return "".join(chr(codepoint) for codepoint in _canonical_compose(ordered))


__all__ = [
    "SOURCE_DIGESTS",
    "TABLE_DIGEST",
    "UNICODE_VERSION",
    "Unicode17Error",
    "is_assigned17",
    "normalize_nfc17",
]
