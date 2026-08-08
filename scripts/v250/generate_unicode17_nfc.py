#!/usr/bin/env python3
"""Generate the pinned, host-independent Unicode 17 NFC tables.

The generator accepts only local UCD inputs.  It verifies their exact byte
lengths and project-pinned SHA-256 digests before parsing them, then emits a
deterministic Python module without timestamps or host ``unicodedata`` use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UCD_ROOT = ROOT / "tests" / "v250" / "fixtures" / "kg262" / "unicode17"
DEFAULT_OUTPUT = Path(__file__).with_name("unicode17_data.py")
UNICODE_VERSION = "17.0.0"

EXPECTED_SOURCES = {
    "UnicodeData.txt": {
        "bytes": 2_198_209,
        "sha256": "2e1efc1dcb59c575eedf5ccae60f95229f706ee6d031835247d843c11d96470c",
    },
    "DerivedNormalizationProps.txt": {
        "bytes": 1_377_582,
        "sha256": "71fd6a206a2c0cdd41feb6b7f656aa31091db45e9cedc926985d718397f9e488",
    },
}

EXPECTED_COUNTS = {
    "canonical_combining_class": 968,
    "canonical_decomposition": 2_081,
    "full_composition_exclusion": 1_120,
    "composition_map": 961,
}


class GenerationError(ValueError):
    """Raised when pinned UCD input or generated table invariants fail."""


def _read_pinned(path: Path, source_name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise GenerationError(f"unsafe or missing local UCD input: {path}")
    raw = path.read_bytes()
    expected = EXPECTED_SOURCES[source_name]
    actual_digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != expected["bytes"]:
        raise GenerationError(
            f"{source_name} byte length mismatch: {len(raw)} != {expected['bytes']}"
        )
    if actual_digest != expected["sha256"]:
        raise GenerationError(
            f"{source_name} SHA-256 mismatch: {actual_digest} != {expected['sha256']}"
        )
    return raw


def _parse_unicode_data(
    raw: bytes,
) -> tuple[
    tuple[tuple[int, int], ...],
    dict[int, int],
    dict[int, tuple[int, ...]],
]:
    combining_classes: dict[int, int] = {}
    decompositions: dict[int, tuple[int, ...]] = {}
    assigned: list[tuple[int, int]] = []
    range_start: tuple[int, str] | None = None

    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        fields = line.split(";")
        if len(fields) != 15:
            raise GenerationError(
                f"UnicodeData.txt:{line_number}: expected 15 fields, got {len(fields)}"
            )
        codepoint = int(fields[0], 16)
        name = fields[1]
        category = fields[2]

        if name.endswith(", First>"):
            if range_start is not None:
                raise GenerationError(
                    f"UnicodeData.txt:{line_number}: nested First range"
                )
            range_start = (codepoint, category)
        elif name.endswith(", Last>"):
            if range_start is None or range_start[1] != category:
                raise GenerationError(
                    f"UnicodeData.txt:{line_number}: unmatched Last range"
                )
            first, first_category = range_start
            if first_category != "Cs":
                assigned.append((first, codepoint))
            range_start = None
        else:
            if range_start is not None:
                raise GenerationError(
                    f"UnicodeData.txt:{line_number}: missing Last range"
                )
            if category != "Cs":
                assigned.append((codepoint, codepoint))

        combining_class = int(fields[3])
        if combining_class:
            combining_classes[codepoint] = combining_class

        decomposition = fields[5]
        if decomposition and not decomposition.startswith("<"):
            decompositions[codepoint] = tuple(
                int(item, 16) for item in decomposition.split()
            )

    if range_start is not None:
        raise GenerationError("UnicodeData.txt: unterminated First range")

    merged: list[tuple[int, int]] = []
    for first, last in sorted(assigned):
        if first < 0 or last > 0x10FFFF or 0xD800 <= first <= 0xDFFF:
            raise GenerationError(
                f"invalid assigned scalar range: U+{first:04X}..U+{last:04X}"
            )
        if merged and first == merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))

    return tuple(merged), combining_classes, decompositions


def _parse_full_composition_exclusions(raw: bytes) -> frozenset[int]:
    exclusions: set[int] = set()
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        payload = line.split("#", 1)[0].strip()
        if not payload:
            continue
        fields = [item.strip() for item in payload.split(";")]
        if len(fields) < 2:
            raise GenerationError(
                "DerivedNormalizationProps.txt:"
                f"{line_number}: malformed property record"
            )
        if fields[1] != "Full_Composition_Exclusion":
            continue
        bounds = fields[0].split("..", 1)
        first = int(bounds[0], 16)
        last = int(bounds[-1], 16)
        exclusions.update(range(first, last + 1))
    return frozenset(exclusions)


def _build_tables(unicode_data: bytes, derived_props: bytes) -> dict[str, Any]:
    assigned, combining_classes, decompositions = _parse_unicode_data(unicode_data)
    exclusions = _parse_full_composition_exclusions(derived_props)
    composition: dict[tuple[int, int], int] = {}
    for composite, decomposition in sorted(decompositions.items()):
        if len(decomposition) != 2 or composite in exclusions:
            continue
        if decomposition in composition:
            previous = composition[decomposition]
            raise GenerationError(
                "duplicate canonical composition pair: "
                f"U+{decomposition[0]:04X} U+{decomposition[1]:04X} -> "
                f"U+{previous:04X}, U+{composite:04X}"
            )
        composition[decomposition] = composite

    actual_counts = {
        "canonical_combining_class": len(combining_classes),
        "canonical_decomposition": len(decompositions),
        "full_composition_exclusion": len(exclusions),
        "composition_map": len(composition),
    }
    if actual_counts != EXPECTED_COUNTS:
        raise GenerationError(
            f"Unicode 17 table count mismatch: {actual_counts} != {EXPECTED_COUNTS}"
        )

    if len(assigned) != 735:
        raise GenerationError(f"assigned scalar range count mismatch: {len(assigned)}")
    assigned_count = sum(last - first + 1 for first, last in assigned)
    if assigned_count != 297_334:
        raise GenerationError(
            f"assigned scalar count mismatch: {assigned_count} != 297334"
        )

    return {
        "assigned_scalar_ranges": assigned,
        "canonical_combining_class": combining_classes,
        "canonical_decomposition": decompositions,
        "composition_map": composition,
    }


def _table_digest(tables: dict[str, Any]) -> str:
    payload = {
        "unicode_version": UNICODE_VERSION,
        "source_digests": {
            name: value["sha256"] for name, value in sorted(EXPECTED_SOURCES.items())
        },
        "assigned_scalar_ranges": [
            [first, last] for first, last in tables["assigned_scalar_ranges"]
        ],
        "canonical_combining_class": [
            [codepoint, value]
            for codepoint, value in sorted(
                tables["canonical_combining_class"].items()
            )
        ],
        "canonical_decomposition": [
            [codepoint, list(value)]
            for codepoint, value in sorted(tables["canonical_decomposition"].items())
        ],
        "composition_map": [
            [first, second, composite]
            for (first, second), composite in sorted(tables["composition_map"].items())
        ],
    }
    canonical = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _render(tables: dict[str, Any]) -> str:
    lines = [
        '"""Generated Unicode 17.0.0 NFC data; do not edit by hand.',
        "",
        "Generated deterministically by scripts/v250/generate_unicode17_nfc.py",
        "from the pinned Unicode Character Database inputs. Unicode data is",
        "used under the Unicode License in tests/v250/fixtures/kg262/unicode17/.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f'UNICODE_VERSION = "{UNICODE_VERSION}"',
        "SOURCE_DIGESTS = {",
    ]
    for name, value in sorted(EXPECTED_SOURCES.items()):
        lines.append(f'    "{name}": "{value["sha256"]}",')
    lines.extend(
        [
            "}",
            f'TABLE_DIGEST = "{_table_digest(tables)}"',
            "",
            "ASSIGNED_SCALAR_RANGES = (",
        ]
    )
    for first, last in tables["assigned_scalar_ranges"]:
        lines.append(f"    (0x{first:06X}, 0x{last:06X}),")
    lines.extend([")", "", "CANONICAL_COMBINING_CLASS = {"])
    for codepoint, value in sorted(tables["canonical_combining_class"].items()):
        lines.append(f"    0x{codepoint:06X}: {value},")
    lines.extend(["}", "", "CANONICAL_DECOMPOSITION = {"])
    for codepoint, value in sorted(tables["canonical_decomposition"].items()):
        rendered = ", ".join(f"0x{item:06X}" for item in value)
        if len(value) == 1:
            rendered += ","
        lines.append(f"    0x{codepoint:06X}: ({rendered}),")
    lines.extend(["}", "", "COMPOSITION_MAP = {"])
    for (first, second), composite in sorted(tables["composition_map"].items()):
        lines.append(
            f"    (0x{first:06X}, 0x{second:06X}): 0x{composite:06X},"
        )
    lines.extend(["}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unicode-data",
        type=Path,
        default=DEFAULT_UCD_ROOT / "UnicodeData.txt",
    )
    parser.add_argument(
        "--derived-normalization-props",
        type=Path,
        default=DEFAULT_UCD_ROOT / "DerivedNormalizationProps.txt",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify generated output without writing",
    )
    args = parser.parse_args()

    unicode_data = _read_pinned(args.unicode_data, "UnicodeData.txt")
    derived_props = _read_pinned(
        args.derived_normalization_props, "DerivedNormalizationProps.txt"
    )
    tables = _build_tables(unicode_data, derived_props)
    rendered = _render(tables)
    existing = (
        args.output.read_text(encoding="utf-8")
        if args.output.is_file() and not args.output.is_symlink()
        else None
    )
    drift = existing != rendered

    if args.check:
        print(
            json.dumps(
                {
                    "ok": not drift,
                    "unicode_version": UNICODE_VERSION,
                    "table_digest": _table_digest(tables),
                    "counts": EXPECTED_COUNTS,
                    "output": str(args.output),
                    "drift": drift,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1 if drift else 0

    if args.output.is_symlink():
        raise GenerationError(f"refusing to replace symlink output: {args.output}")
    if drift:
        args.output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "unicode_version": UNICODE_VERSION,
                "table_digest": _table_digest(tables),
                "counts": EXPECTED_COUNTS,
                "output": str(args.output),
                "updated": drift,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
