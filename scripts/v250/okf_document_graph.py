#!/usr/bin/env python3
"""Transient, document-only OKF knowledge graph for Goal Teams V2.62.

The Markdown files selected by one trusted ``knowledge-map.md`` remain the
only persistent source.  This module reads that exact closure into a fresh
in-memory RDF-compatible view.  It deliberately has no database, network,
cache, graph serialization, or writer code.

This is an OKF application profile adapter, not a general Markdown, RDF,
SHACL, or SPARQL implementation.  Quality findings are observations whose
current action is always ``record``.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

from scripts.v250.unicode17_nfc import (
    Unicode17Error,
    is_assigned17,
    normalize_nfc17 as _normalize_nfc17,
)


PROFILE_ID = "okf-document-graph-v0.4-rdf-mapping"
GRAPH_INPUT_SCHEMA = "okf-docgraph-graph-input-v0.4"
PARSER_CONTRACT_ID = "okf-frontmatter-commonmark-gfm-table-v0.4"
PERSISTENCE_STATE = "not_run"

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCTERMS = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
XSD = "http://www.w3.org/2001/XMLSchema#"

CAPABILITIES = {
    "rdf_view": "implemented",
    "sparql_state": "not_implemented",
    "shacl_engine_state": "not_implemented",
    "rdfs_owl_reasoning_state": "not_implemented",
}

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ROUTE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_XSD_DATETIME_STAMP_RE = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])-"
    r"(?P<day>0[1-9]|[12][0-9]|3[01])T"
    r"(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.[0-9]+)?"
    r"(?P<zone>Z|(?P<zone_sign>[+-])(?P<zone_hour>0[0-9]|1[0-4]):"
    r"(?P<zone_minute>[0-5][0-9]))$"
)
_CLAIM_HEADING_RE = re.compile(r"^###\s+(`?)([^`\s]+)\1\s*$")
_REFERENCE_RE = re.compile(
    r"^(?P<namespace>[^:@#\s]+):(?P<knowledge_id>[^@#\s]+)"
    r"@(?P<revision>[^#\s]+)(?:#(?P<claim_id>[^#\s]+))?$"
)
_IDENTITY_COMPONENT_FIELDS = ("namespace", "knowledge_id", "revision")
_IDENTITY_COMPONENT_DELIMITERS = frozenset(":@#")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_FENCE_OPEN_RE = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>.*)$"
)
_HTML_BLOCK_TAG_RE = re.compile(
    r"^<(?P<closing>/)?(?P<tag>[A-Za-z][A-Za-z0-9-]*)(?=[ \t]|/?>|$)",
    re.IGNORECASE,
)
_HTML_RAW_TAG_RE = re.compile(
    r"^<(script|pre|style|textarea)(?:[ \t]|>|$)", re.IGNORECASE
)
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_NETWORK_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_UNRESERVED = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)

# macOS exposes these immutable, OS-owned compatibility aliases.  They are
# outside the injected knowledge root and are resolved before the trust root is
# captured.  Every other symlink at or above the lexical root fails closed.
_DARWIN_SYSTEM_ALIASES = {
    "/etc": "/private/etc",
    "/tmp": "/private/tmp",
    "/var": "/private/var",
}
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd

_PREDICATES = {
    "DERIVED_FROM": PROV + "wasDerivedFrom",
    "SUPERSEDES": DCTERMS + "replaces",
    "RELATED_TO": None,  # requires a SKOS Concept model, not inferred here
    "HAS_AC": "hasAcceptanceCriterion",
    "DEPENDS_ON": "dependsOn",
    "IMPLEMENTS": "implements",
    "VERIFIES": "verifies",
    "SUPPORTS": "supports",
    "REFUTES": "refutes",
    "CONFLICTS_WITH": "conflictsWith",
}

_TYPE_NAMES = {
    "Knowledge Requirement": "KnowledgeRequirement",
    "Knowledge Acceptance Criterion": "KnowledgeAcceptanceCriterion",
    "Knowledge Evidence": "KnowledgeEvidence",
    "Knowledge Note": "KnowledgeNote",
    "Knowledge Map": "KnowledgeCollection",
}


class GraphSecurityError(ValueError):
    """Stable security-boundary failure returned by the graph adapter."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")


def normalize_nfc17(text: str) -> str:
    """Normalize with the repository-pinned Unicode 17 implementation.

    Unicode-version failures are mapped to the graph adapter's stable public
    security error rather than leaking implementation-specific exceptions.
    """

    if not isinstance(text, str):
        raise TypeError("normalize_nfc17 expects str")
    if any(not is_assigned17(ord(character)) for character in text):
        raise GraphSecurityError(
            "E_KG262_UNICODE_UNASSIGNED",
            "input contains a scalar unassigned in Unicode 17.0.0",
        )
    try:
        return _normalize_nfc17(text)
    except Unicode17Error as exc:
        raise GraphSecurityError(
            "E_KG262_UNICODE_UNASSIGNED",
            "input contains a scalar unassigned in Unicode 17.0.0",
        ) from exc


def pct_segment(value: str) -> str:
    """Mint one RFC 3986 path segment from Unicode-17 NFC UTF-8 bytes."""

    normalized = normalize_nfc17(value)
    encoded = normalized.encode("utf-8")
    if normalized in {".", ".."}:
        return "%2E" * len(normalized)
    return "".join(
        chr(byte) if byte in _UNRESERVED else f"%{byte:02X}" for byte in encoded
    )


@dataclass(frozen=True, order=True)
class Triple:
    """One RDF-compatible triple in the transient graph."""

    subject: str
    predicate: str
    object: str
    object_kind: str = "iri"
    datatype: str | None = None
    language: str | None = None


def _literal(
    subject: str,
    predicate: str,
    value: str,
    *,
    datatype: str | None = None,
    language: str | None = None,
) -> Triple:
    return Triple(subject, predicate, value, "literal", datatype, language)


def _iri(subject: str, predicate: str, value: str) -> Triple:
    return Triple(subject, predicate, value, "iri")


def _strip_markup(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "`":
        value = value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _controlled_text(value: Any) -> str:
    """Return one normalized controlled literal or the empty missing value."""

    return _strip_markup(value) if isinstance(value, str) else ""


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_markup(item) for item in inner.split(",")]
    if value in {"null", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _frontmatter(
    text: str,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines, []
    try:
        closing = next(
            index for index in range(1, len(lines)) if lines[index].strip() == "---"
        )
    except StopIteration:
        return {}, lines, []
    values: dict[str, Any] = {}
    diagnostics: list[dict[str, Any]] = []
    first_lines: dict[str, int] = {}
    for line_number, line in enumerate(lines[1:closing], start=2):
        stripped_line = line.strip()
        if not stripped_line or line.lstrip().startswith("#"):
            continue
        line_yaml_token = re.search(
            r"(?:^|[\s\[,])([!&*])(?:!|[A-Za-z_])", stripped_line
        )
        if ":" not in line:
            if line_yaml_token:
                diagnostics.append(
                    {
                        "rule_id": "yaml_graph_syntax_literalized",
                        "detail": {
                            "key": None,
                            "line": line_number,
                            "syntax": {
                                "!": "tag",
                                "&": "anchor",
                                "*": "alias",
                            }[line_yaml_token.group(1)],
                            "parser_action": "literal_text",
                        },
                    }
                )
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw_value = raw.strip()
        if key in first_lines:
            diagnostics.append(
                {
                    "rule_id": "duplicate_frontmatter_key",
                    "detail": {
                        "key": key,
                        "first_line": first_lines[key],
                        "duplicate_line": line_number,
                        "parser_action": "last_literal_value_selected",
                    },
                }
            )
        else:
            first_lines[key] = line_number
        yaml_token = re.search(
            r"(?:^|[\s\[,])([!&*])(?:!|[A-Za-z_])", raw_value
        )
        if key == "<<" or yaml_token:
            diagnostics.append(
                {
                    "rule_id": "yaml_graph_syntax_literalized",
                    "detail": {
                        "key": key,
                        "line": line_number,
                        "syntax": (
                            "merge"
                            if key == "<<"
                            else {"!": "tag", "&": "anchor", "*": "alias"}.get(
                                yaml_token.group(1) if yaml_token else "", "directive"
                            )
                        ),
                        "parser_action": "literal_text",
                    },
                }
            )
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            values[key] = _parse_scalar(raw)
    return values, lines[closing + 1 :], diagnostics


def _identity_component_findings(
    frontmatter: dict[str, Any],
) -> list[dict[str, str]]:
    """Return syntax findings for components embedded in ``ns:id@revision``.

    The three frontmatter components share one deliberately small grammar:
    they are non-empty strings without the ``:``, ``@``, or ``#`` reference
    delimiters, whitespace, or C0/C1 control characters.  Other Unicode is
    retained and is handled by the pinned Unicode-17 normalization boundary.
    """

    findings: list[dict[str, str]] = []
    for field in _IDENTITY_COMPONENT_FIELDS:
        value = frontmatter.get(field)
        if not isinstance(value, str) or not value:
            continue
        forbidden = next(
            (
                character
                for character in value
                if character in _IDENTITY_COMPONENT_DELIMITERS
                or character.isspace()
                or ord(character) <= 0x1F
                or 0x7F <= ord(character) <= 0x9F
            ),
            None,
        )
        if forbidden is not None:
            findings.append(
                {
                    "field": field,
                    "value": value,
                    "forbidden_codepoint": f"U+{ord(forbidden):04X}",
                    "grammar": "nonempty; no : @ #, whitespace, or C0/C1 control",
                }
            )
    return findings


def _qualified_ref(frontmatter: dict[str, Any]) -> str | None:
    parts = (
        frontmatter.get("namespace"),
        frontmatter.get("knowledge_id"),
        frontmatter.get("revision"),
    )
    if (
        not all(isinstance(item, str) and item for item in parts)
        or _identity_component_findings(frontmatter)
    ):
        return None
    return f"{parts[0]}:{parts[1]}@{parts[2]}"


def _active_markdown_lines(lines: list[str]) -> list[str]:
    """Mask syntax inside Markdown blocks that cannot carry graph facts.

    This intentionally implements only the lexical boundary needed by the OKF
    profile: fenced and indented code, HTML comments, and raw HTML blocks are
    inactive.  Complete, closing, void, and self-closing HTML block starts are
    blank-line terminated; raw script-like containers remain close-tag
    terminated.  The returned list retains the input length so claim-section
    boundaries stay deterministic.  Inline HTML comments are removed while
    preserving active text outside the comment.
    """

    active: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    in_html_comment = False
    html_raw_terminator: str | None = None
    html_raw_tag: str | None = None
    html_blank_terminated_block = False

    for source_line in lines:
        if fence_character is not None:
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}"
                rf"{{{fence_length},}}[ \t]*",
                source_line,
            )
            if closing:
                fence_character = None
                fence_length = 0
            active.append("")
            continue

        if html_raw_terminator is not None:
            if html_raw_terminator.casefold() in source_line.casefold():
                html_raw_terminator = None
            active.append("")
            continue

        if html_raw_tag is not None:
            if re.match(
                rf"^ {{0,3}}</{re.escape(html_raw_tag)}[ \t]*>",
                source_line,
                re.IGNORECASE,
            ):
                html_raw_tag = None
            active.append("")
            continue

        if html_blank_terminated_block:
            if not source_line.strip():
                html_blank_terminated_block = False
            active.append("")
            continue

        # A block comment that began on an earlier line owns its complete
        # terminator line.  Text following ``-->`` on that line is not active
        # Markdown; only a genuinely inline same-line comment may preserve
        # active text on both sides.
        if in_html_comment:
            if "-->" in source_line:
                in_html_comment = False
            active.append("")
            continue

        leading_comment = re.match(r"^ {0,3}<!--", source_line)
        if leading_comment is not None:
            if "-->" not in source_line[leading_comment.end() :]:
                in_html_comment = True
            active.append("")
            continue

        # Remove all comment spans on this line.  A comment may start or end
        # mid-line; only text outside it remains eligible for profile syntax.
        fragments: list[str] = []
        cursor = 0
        while cursor < len(source_line):
            if in_html_comment:
                comment_end = source_line.find("-->", cursor)
                if comment_end < 0:
                    cursor = len(source_line)
                    break
                in_html_comment = False
                cursor = comment_end + 3
                continue
            comment_start = source_line.find("<!--", cursor)
            if comment_start < 0:
                fragments.append(source_line[cursor:])
                cursor = len(source_line)
                break
            fragments.append(source_line[cursor:comment_start])
            in_html_comment = True
            cursor = comment_start + 4
        line = "".join(fragments)
        if not line.strip():
            active.append("")
            continue

        # Four-space and tab indentation is code in the supported profile.
        if re.match(r"^(?: {4}| {0,3}\t)", line):
            active.append("")
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence is not None:
            marker = fence.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            active.append("")
            continue

        stripped = line.lstrip(" ")
        lowered = stripped.casefold()
        terminator: str | None = None
        if lowered.startswith("<?"):
            terminator = "?>"
        elif lowered.startswith("<![cdata["):
            terminator = "]]>"
        elif re.match(r"^<![A-Z]", stripped):
            terminator = ">"
        else:
            raw_tag = _HTML_RAW_TAG_RE.match(stripped)
            if raw_tag is not None:
                tag = raw_tag.group(1).casefold()
                if re.search(
                    rf"</{re.escape(tag)}[ \t]*>", stripped, re.IGNORECASE
                ) is None:
                    html_raw_tag = tag
                active.append("")
                continue
        if terminator is not None:
            if terminator.casefold() not in lowered:
                html_raw_terminator = terminator
            active.append("")
            continue
        block_tag = _HTML_BLOCK_TAG_RE.match(stripped)
        if block_tag is not None:
            # CommonMark HTML block types 6 and 7 end at the first blank line,
            # including opening tags that have not yet closed.  Type-1
            # script/pre/style/textarea blocks were handled above and retain
            # close-tag termination.
            html_blank_terminated_block = True
            active.append("")
            continue

        active.append(line)
    return active


def _table_rows(lines: list[str], heading: str) -> list[dict[str, str]]:
    lines = _active_markdown_lines(lines)
    wanted = heading.casefold()
    start: int | None = None
    for index, line in enumerate(lines):
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if match and _strip_markup(match.group(1)).casefold() == wanted:
            start = index + 1
            break
    if start is None:
        return []
    table: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        if line.strip().startswith("|"):
            table.append(line.strip())
        elif table:
            break
    if len(table) < 2:
        return []

    def cells(line: str) -> list[str]:
        return [item.strip() for item in line.strip().strip("|").split("|")]

    headers = [_strip_markup(item) for item in cells(table[0])]
    separator = cells(table[1])
    if len(separator) != len(headers) or not all(
        re.fullmatch(r":?-{3,}:?", item.replace(" ", "")) for item in separator
    ):
        return []
    rows: list[dict[str, str]] = []
    for line in table[2:]:
        values = cells(line)
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def _extract_link(value: str) -> str | None:
    match = _MARKDOWN_LINK_RE.search(value)
    return match.group(1).strip() if match else None


def _canonical_map_path(raw: str) -> str:
    """Validate one exact map member path without URL decoding."""

    if _NETWORK_SCHEME_RE.match(raw) or raw.startswith("//"):
        raise GraphSecurityError(
            "E_KG262_NETWORK_FORBIDDEN", "network map members are forbidden"
        )
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise GraphSecurityError(
            "E_KG262_NETWORK_FORBIDDEN", "URI map members are forbidden"
        )
    if parsed.query or parsed.fragment:
        raise GraphSecurityError(
            "E_KG262_PATH_ESCAPE", "map members must be plain relative paths"
        )
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or any(
        part in {"", ".", ".."} for part in pure.parts
    ):
        raise GraphSecurityError(
            "E_KG262_PATH_ESCAPE", "map member escapes its trusted root"
        )
    return PurePosixPath(*(normalize_nfc17(part) for part in pure.parts)).as_posix()


def _is_allowed_system_alias(path: Path) -> bool:
    if sys.platform != "darwin":
        return False
    expected = _DARWIN_SYSTEM_ALIASES.get(path.as_posix())
    if expected is None:
        return False
    try:
        return path.resolve(strict=True).as_posix() == expected
    except (OSError, RuntimeError):
        return False


def _trusted_root(value: Path | str) -> Path:
    lexical = Path(value).absolute()
    # Check the injected root and every lexical ancestor.  An ancestor symlink
    # can otherwise redirect the whole allowlist between path checks.
    for candidate in (lexical, *lexical.parents):
        if candidate.is_symlink() and not _is_allowed_system_alias(candidate):
            raise GraphSecurityError(
                "E_KG262_PATH_SYMLINK",
                "knowledge root or one of its ancestors is a symlink",
            )
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GraphSecurityError(
            "E_KG262_PATH_ESCAPE", "knowledge root is not a readable directory"
        ) from exc
    if not resolved.is_dir():
        raise GraphSecurityError(
            "E_KG262_PATH_ESCAPE", "knowledge root is not a directory"
        )
    return resolved


def _safe_file(root: Path, relative: str) -> Path:
    # ``root`` is already canonicalized by _trusted_root.  Every member
    # component (including an intermediate directory) is checked with lstat
    # semantics before any file bytes are read.
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GraphSecurityError(
                "E_KG262_PATH_SYMLINK", "symlink members are forbidden"
            )
    try:
        candidate.absolute().relative_to(root)
    except ValueError as exc:
        raise GraphSecurityError(
            "E_KG262_PATH_ESCAPE", "member escapes its trusted root"
        ) from exc
    return candidate


def _safe_read_bytes(root: Path, relative: str) -> bytes | None:
    """Read one allowlisted file through descriptor-relative no-follow opens.

    The directory descriptor chain closes the lstat/check-to-read symlink swap
    window for every member component.  Platforms without ``dir_fd`` and
    ``O_NOFOLLOW`` support fail closed rather than falling back to Path.read.
    """

    if not _OPEN_SUPPORTS_DIR_FD or not hasattr(os, "O_NOFOLLOW"):
        raise GraphSecurityError(
            "E_KG262_SAFE_READ_UNAVAILABLE",
            "descriptor-relative no-follow reads are unavailable",
        )
    parts = PurePosixPath(relative).parts
    if not parts:
        raise GraphSecurityError("E_KG262_PATH_ESCAPE", "empty member path")
    common = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    directory_flags = common | getattr(os, "O_DIRECTORY", 0)
    file_flags = common | getattr(os, "O_NONBLOCK", 0)
    descriptors: list[int] = []
    try:
        if not root.is_absolute():
            raise GraphSecurityError(
                "E_KG262_PATH_ESCAPE", "trusted root must be absolute"
            )
        current = os.open(root.anchor, directory_flags)
        descriptors.append(current)
        for component in root.parts[1:]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise GraphSecurityError(
                "E_KG262_PATH_SYMLINK", "map members must be regular files"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise GraphSecurityError(
                "E_KG262_PATH_SYMLINK",
                "member or an intermediate component became a symlink",
            ) from exc
        if exc.errno in {errno.EACCES, errno.EPERM}:
            return None
        raise GraphSecurityError(
            "E_KG262_SAFE_READ_FAILED", "descriptor-bound member read failed"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _canonical_body_link(source_path: str, raw_link: str) -> str | None:
    """Resolve a body link lexically; this function never reads its target."""

    if _NETWORK_SCHEME_RE.match(raw_link) or raw_link.startswith("//"):
        return None
    parsed = urlsplit(raw_link)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    joined = posixpath.normpath(
        posixpath.join(posixpath.dirname(source_path), parsed.path)
    )
    if joined == ".." or joined.startswith("../") or joined.startswith("/"):
        return None
    pure = PurePosixPath(joined)
    if any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return PurePosixPath(*(normalize_nfc17(part) for part in pure.parts)).as_posix()


def _body_link_identity(
    source_path: str, raw_link: str
) -> tuple[str | None, str | None]:
    parsed = urlsplit(raw_link)
    if parsed.query:
        return None, None
    return _canonical_body_link(source_path, raw_link), parsed.fragment or None


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _XSD_DATETIME_STAMP_RE.fullmatch(value)
    if match is None:
        return False
    if match.group("zone_hour") == "14" and match.group("zone_minute") != "00":
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _observation(
    rule_id: str,
    subject_ref: str,
    detail: dict[str, Any],
    *,
    severity: str = "warning",
) -> dict[str, Any]:
    canonical = json.dumps(
        {"rule_id": rule_id, "subject_ref": subject_ref, "detail": detail},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suffix = hashlib.sha256(canonical).hexdigest()[:20].upper()
    return {
        "finding_id": f"OBS-KG262-{suffix}",
        "rule_id": rule_id,
        "severity": severity,
        "subject_ref": subject_ref,
        "observation_state": "unresolved",
        "detail": detail,
        "validation_state": "nonconforms",
        "run_status": "completed",
        "current_action": "record",
        "future_action": "undecided",
    }


def _claim_sections(body: list[str]) -> list[dict[str, Any]]:
    body = _active_markdown_lines(body)
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(body):
        match = _CLAIM_HEADING_RE.match(line.strip())
        if match and match.group(2).startswith("CLM-"):
            starts.append((index, match.group(2)))
    sections: list[dict[str, Any]] = []
    for start, claim_id in starts:
        end = len(body)
        for index in range(start + 1, len(body)):
            if re.match(r"^ {0,3}#{1,3}(?:[ \t]+|$)", body[index]):
                end = index
                break
        lines = body[start + 1 : end]
        claim_text_lines: list[str] = []
        for line in lines:
            if re.match(r"^####\s+", line):
                break
            if line.strip() and not line.strip().startswith("|"):
                claim_text_lines.append(line.strip())
        relations = _table_rows(lines, "Relations")
        evidence_links: list[str] = []
        in_evidence = False
        for line in lines:
            heading = re.match(r"^####\s+(.+?)\s*$", line)
            if heading:
                in_evidence = heading.group(1).casefold() == "evidence"
                continue
            if in_evidence:
                link = _extract_link(line)
                if link:
                    evidence_links.append(link)
        sections.append(
            {
                "claim_id": claim_id,
                "claim_text": "\n".join(claim_text_lines).strip(),
                "relations": relations,
                "evidence_links": evidence_links,
            }
        )
    return sections


def _predicate_iri(base: str, name: str) -> str | None:
    key = _strip_markup(name).upper()
    mapped = _PREDICATES.get(key)
    if mapped is None:
        return None
    if mapped.startswith("http://") or mapped.startswith("https://"):
        return mapped
    return base + "/vocab/" + mapped


def _reference_parts(reference: str) -> dict[str, str] | None:
    match = _REFERENCE_RE.fullmatch(reference)
    return match.groupdict() if match else None


def _replay_namespace_version(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    components = value.split(".")
    for index, component in enumerate(components):
        if component.casefold() == "replay" and index + 1 < len(components):
            suffix = ".".join(components[index + 1 :])
            return suffix or None
    return None


def _is_replay_namespace(value: Any) -> bool:
    return isinstance(value, str) and any(
        component.casefold() == "replay" for component in value.split(".")
    )


def _document_iris(base: str, frontmatter: dict[str, Any]) -> tuple[str, str]:
    stable = (
        base
        + "/resource/"
        + pct_segment(str(frontmatter["namespace"]))
        + "/"
        + pct_segment(str(frontmatter["knowledge_id"]))
    )
    return stable, stable + "/revision/" + pct_segment(str(frontmatter["revision"]))


def _claim_iris(
    base: str, frontmatter: dict[str, Any], claim_id: str
) -> tuple[str, str]:
    stable = (
        base
        + "/claim/"
        + pct_segment(str(frontmatter["namespace"]))
        + "/"
        + pct_segment(str(frontmatter["knowledge_id"]))
        + "/"
        + pct_segment(claim_id)
    )
    return stable, stable + "/revision/" + pct_segment(str(frontmatter["revision"]))


def _validate_base_iri(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.endswith("/")
        or "\\" in value
        or "?" in value
        or "#" in value
        or any(character in value for character in '<>"{}|^`')
        or any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise GraphSecurityError(
            "E_KG262_INVALID_BASE_IRI", "kg_base_iri must be normalized HTTPS"
        )
    try:
        parsed = urlsplit(value)
        parsed_port = parsed.port
        normalized = normalize_nfc17(value)
    except (ValueError, GraphSecurityError) as exc:
        raise GraphSecurityError(
            "E_KG262_INVALID_BASE_IRI", "kg_base_iri must be normalized HTTPS"
        ) from exc
    raw_host = parsed.netloc.rsplit("@", 1)[-1]
    if raw_host.startswith("["):
        host_spelling = raw_host.split("]", 1)[0] + "]"
    else:
        host_spelling = raw_host.split(":", 1)[0]
    percent_tokens = list(re.finditer(r"%([0-9A-Fa-f]{2})", value))
    percent_count = value.count("%")
    percent_is_canonical = percent_count == len(percent_tokens)
    for token in percent_tokens:
        spelling = token.group(1)
        decoded = int(spelling, 16)
        if spelling != spelling.upper() or decoded in _UNRESERVED:
            percent_is_canonical = False
            break
    path_segments = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "[" in parsed.path
        or "]" in parsed.path
        or normalized != value
        or host_spelling != host_spelling.lower()
        or "%" in parsed.netloc
        or parsed.hostname.endswith(".")
        or parsed_port == 443
        or any(segment in {".", ".."} for segment in path_segments)
        or "//" in parsed.path
        or not percent_is_canonical
    ):
        raise GraphSecurityError(
            "E_KG262_INVALID_BASE_IRI", "kg_base_iri must be normalized HTTPS"
        )


def _validate_hash(value: str, field: str) -> None:
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise GraphSecurityError(
            "E_KG262_IDENTITY_INVALID", f"{field} must be lowercase SHA-256"
        )


def _validate_route(value: str) -> None:
    if not isinstance(value, str) or not _ROUTE_RE.fullmatch(value):
        raise GraphSecurityError(
            "E_KG262_IDENTITY_INVALID",
            "route_identity must be sha256:<lowercase-64-hex>",
        )


class DocumentGraph:
    """A fresh exact graph compiled entirely in memory."""

    def __init__(
        self,
        *,
        graph_role: str,
        route_identity: str,
        acceptance_eligible: bool,
        graph_input: dict[str, Any],
        graph_input_sha256: str,
        graph_iri: str,
        kg_base_iri: str,
        member_paths: tuple[str, ...],
        documents: dict[str, dict[str, Any]],
        claims: dict[str, dict[str, Any]],
        triples: tuple[Triple, ...],
        statements: tuple[dict[str, Any], ...],
        observations: tuple[dict[str, Any], ...],
        edges: tuple[dict[str, Any], ...],
    ) -> None:
        self._graph_role = graph_role
        self._route_identity = route_identity
        self._acceptance_eligible = acceptance_eligible
        self._graph_input = copy.deepcopy(graph_input)
        self._graph_input_sha256 = graph_input_sha256
        self._graph_iri = graph_iri
        self._kg_base_iri = kg_base_iri
        self._member_paths = tuple(member_paths)
        self._documents = copy.deepcopy(documents)
        self._triples = tuple(triples)
        self._statements = copy.deepcopy(statements)
        self._observations = copy.deepcopy(observations)
        self._coverage_state = "partial" if observations else "complete"
        self._capabilities = dict(CAPABILITIES)
        self._persistence_state = PERSISTENCE_STATE
        self._claims = copy.deepcopy(claims)
        self._edges = copy.deepcopy(edges)
        self._iri_to_ref = {
            item["occurrence_iri"]: reference for reference, item in claims.items()
        }
        self._ref_to_iri = {
            reference: item["occurrence_iri"] for reference, item in claims.items()
        }
        for reference, item in documents.items():
            self._iri_to_ref[item["revision_iri"]] = reference
            self._ref_to_iri[reference] = item["revision_iri"]

    @property
    def graph_input(self) -> dict[str, Any]:
        return copy.deepcopy(self._graph_input)

    @property
    def graph_role(self) -> str:
        return self._graph_role

    @property
    def route_identity(self) -> str:
        return self._route_identity

    @property
    def acceptance_eligible(self) -> bool:
        return self._acceptance_eligible

    @property
    def graph_iri(self) -> str:
        return self._graph_iri

    @property
    def member_paths(self) -> tuple[str, ...]:
        return self._member_paths

    @property
    def graph_input_sha256(self) -> str:
        return self._graph_input_sha256

    @property
    def triples(self) -> tuple[Triple, ...]:
        return self._triples

    @property
    def coverage_state(self) -> str:
        return self._coverage_state

    @property
    def persistence_state(self) -> str:
        return self._persistence_state

    @property
    def documents(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._documents)

    @property
    def statements(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._statements)

    @property
    def observations(self) -> tuple[dict[str, Any], ...]:
        return copy.deepcopy(self._observations)

    @property
    def capabilities(self) -> dict[str, str]:
        return dict(self._capabilities)

    def _receipt(
        self,
        query_kind: str,
        results: list[dict[str, Any]],
        *,
        limit: int,
        truncated: bool,
        total_count: int | None = None,
    ) -> dict[str, Any]:
        match_count = len(results) if total_count is None else total_count
        if query_kind == "observe":
            match_state = "not_applicable"
        elif match_count == 0:
            match_state = "none"
        elif match_count == 1:
            match_state = "unique"
        else:
            match_state = "multiple"
        if query_kind in {"resolve", "explain"}:
            ambiguity_state = "ambiguous" if match_count > 1 else "unambiguous"
        else:
            ambiguity_state = "not_applicable"
        return {
            "query_kind": query_kind,
            "graph_role": self.graph_role,
            "graph_iri": self.graph_iri,
            "graph_input_sha256": self.graph_input_sha256,
            "route_identity": self.route_identity,
            "acceptance_eligible": self.acceptance_eligible,
            "coverage_state": self.coverage_state,
            "run_status": "completed",
            "current_action": "record",
            "persistence": PERSISTENCE_STATE,
            "match_state": match_state,
            "match_count": match_count,
            "ambiguity_state": ambiguity_state,
            "limit": limit,
            "truncated": truncated,
            "results": copy.deepcopy(results),
        }

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return min(limit, 10_000)

    def to_receipt(self) -> dict[str, Any]:
        return {
            "schema": "okf-docgraph-receipt-v0.4",
            "graph_role": self.graph_role,
            "graph_iri": self.graph_iri,
            "graph_input_sha256": self.graph_input_sha256,
            "route_identity": self.route_identity,
            "acceptance_eligible": self.acceptance_eligible,
            "coverage_state": self.coverage_state,
            "capabilities": dict(self._capabilities),
            "persistence_state": self.persistence_state,
            "document_count": len(self._documents),
            "triple_count": len(self.triples),
            "statement_count": len(self._statements),
            "observation_count": len(self._observations),
        }

    def observe(self, *, limit: int = 1000) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        values = copy.deepcopy(list(self._observations))
        for item in values:
            item["result_kind"] = "observation"
        result = self._receipt(
            "observe",
            values[:limit],
            limit=limit,
            truncated=len(values) > limit,
            total_count=len(values),
        )
        result["future_action"] = "undecided"
        return result

    def resolve(self, reference: str, *, limit: int = 100) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        values: list[dict[str, Any]] = []
        if reference in self._claims:
            item = copy.deepcopy(self._claims[reference])
            item["result_kind"] = "claim"
            values.append(item)
        elif reference in self._documents:
            item = copy.deepcopy(self._documents[reference])
            item["result_kind"] = "document"
            values.append(item)
        else:
            # Stable resource references resolve to their exact in-graph revisions.
            prefix = reference + "@"
            candidates = [
                (key, copy.deepcopy(value))
                for key, value in {**self._documents, **self._claims}.items()
                if key.startswith(prefix)
            ]
            for key, item in sorted(candidates, key=lambda pair: pair[0]):
                item["result_kind"] = (
                    "claim" if key in self._claims else "document"
                )
                values.append(item)
        return self._receipt(
            "resolve",
            values[:limit],
            limit=limit,
            truncated=len(values) > limit,
            total_count=len(values),
        )

    def search(self, text: str, *, limit: int = 100) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        needle = normalize_nfc17(text).casefold().strip()
        matches: list[dict[str, Any]] = []
        if needle:
            for reference in sorted(self._documents, key=lambda value: value.encode("utf-8")):
                document = self._documents[reference]
                claims = [
                    item
                    for item in self._claims.values()
                    if item["document_ref"] == reference
                ]
                haystack = "\n".join(
                    [
                        reference,
                        document.get("title", ""),
                        document.get("description", ""),
                        document.get("path", ""),
                        " ".join(document.get("aliases", [])),
                        *(item.get("claim_text", "") for item in claims),
                    ]
                ).casefold()
                if needle in haystack:
                    matches.append(
                        {
                            "result_kind": "search_hit",
                            "reference": reference,
                            "path": document["path"],
                            "title": document.get("title", ""),
                            "description": document.get("description", ""),
                            "claim_refs": [item["reference"] for item in claims],
                            "source_sha256": document["source_sha256"],
                            "revision_digest": document["revision_digest"],
                            "source_anchor": document["source_anchor"],
                            "extraction_state": document["extraction_state"],
                            "graph_iri": self.graph_iri,
                            "graph_input_sha256": self.graph_input_sha256,
                        }
                    )
        return self._receipt(
            "search",
            matches[:limit],
            limit=limit,
            truncated=len(matches) > limit,
            total_count=len(matches),
        )

    def neighbors(
        self,
        reference: str,
        *,
        direction: str = "both",
        predicate: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be in, out, or both")
        iri = self._ref_to_iri.get(reference, reference if reference in self._iri_to_ref else None)
        wanted_predicate = None
        if predicate:
            wanted_predicate = (
                predicate
                if predicate.startswith("http://") or predicate.startswith("https://")
                else _predicate_iri(self._kg_base_iri, predicate)
            )
            if wanted_predicate is None:
                return self._receipt(
                    "neighbors", [], limit=limit, truncated=False
                )
        values: list[dict[str, Any]] = []
        if iri:
            for edge in self._edges:
                outbound = edge["subject"] == iri
                inbound = edge["object"] == iri
                if not (
                    (direction in {"out", "both"} and outbound)
                    or (direction in {"in", "both"} and inbound)
                ):
                    continue
                if wanted_predicate and edge["predicate"] != wanted_predicate:
                    continue
                values.append(dict(edge))
        values.sort(
            key=lambda item: (
                item["subject"].encode("utf-8"),
                item["predicate"].encode("utf-8"),
                item["object"].encode("utf-8"),
            )
        )
        return self._receipt(
            "neighbors",
            values[:limit],
            limit=limit,
            truncated=len(values) > limit,
            total_count=len(values),
        )

    def trace(
        self, reference: str, *, max_depth: int = 3, limit: int = 100
    ) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        start = self._ref_to_iri.get(reference, reference if reference in self._iri_to_ref else None)
        values: list[dict[str, Any]] = []
        if start:
            visited = {start}
            frontier = [(start, 0)]
            while frontier and len(values) <= limit:
                node, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                outgoing = sorted(
                    (edge for edge in self._edges if edge["subject"] == node),
                    key=lambda item: (
                        item["predicate"].encode("utf-8"),
                        item["object"].encode("utf-8"),
                    ),
                )
                for edge in outgoing:
                    item = dict(edge)
                    item["depth"] = depth + 1
                    values.append(item)
                    if edge["object"] not in visited:
                        visited.add(edge["object"])
                        frontier.append((edge["object"], depth + 1))
        return self._receipt(
            "trace",
            values[:limit],
            limit=limit,
            truncated=len(values) > limit,
            total_count=len(values),
        )

    def explain(self, reference: str, *, limit: int = 100) -> dict[str, Any]:
        limit = self._bounded_limit(limit)
        claims_to_explain: list[dict[str, Any]] = []
        claim = self._claims.get(reference)
        if claim is not None:
            claims_to_explain = [claim]
        elif reference in self._documents:
            claims_to_explain = sorted(
                (
                    item
                    for item in self._claims.values()
                    if item["document_ref"] == reference
                ),
                key=lambda item: item["reference"].encode("utf-8"),
            )
        values: list[dict[str, Any]] = []
        for claim in claims_to_explain:
            document = self._documents[claim["document_ref"]]
            related = [
                dict(edge)
                for edge in self._edges
                if edge["subject"] == claim["occurrence_iri"]
                or edge["object"] == claim["occurrence_iri"]
            ]
            values.append(
                {
                    "result_kind": "explanation",
                    "reference": claim["reference"],
                    "claim_text": claim["claim_text"],
                    "document_ref": claim["document_ref"],
                    "document_path": document["path"],
                    "title": document.get("title", ""),
                    "description": document.get("description", ""),
                    "evidence_paths": list(claim.get("evidence_paths", [])),
                    "evidence_refs": list(claim.get("evidence_refs", [])),
                    "asserted_relations": related,
                    "source_sha256": claim["source_sha256"],
                    "revision_digest": claim["revision_digest"],
                    "source_anchor": claim["source_anchor"],
                    "extraction_state": claim["extraction_state"],
                    "graph_iri": self.graph_iri,
                    "graph_input_sha256": self.graph_input_sha256,
                }
            )
        return self._receipt(
            "explain",
            values[:limit],
            limit=limit,
            truncated=len(values) > limit,
            total_count=len(values),
        )

    def has_triple(self, subject: str, predicate: str, object_: str) -> bool:
        return any(
            triple.subject == subject
            and triple.predicate == predicate
            and triple.object == object_
            for triple in self.triples
        )


def _compile_graph(
    root: Path | str,
    entry_map: str,
    *,
    graph_role: str,
    kg_base_iri: str,
    route_identity: str,
    profile_document_sha256: str,
    replay_version: str | None = None,
    snapshot_sha256: str | None = None,
) -> DocumentGraph:
    _validate_base_iri(kg_base_iri)
    _validate_route(route_identity)
    _validate_hash(profile_document_sha256, "profile_document_sha256")
    if graph_role == "replay":
        if not isinstance(replay_version, str) or not replay_version:
            raise GraphSecurityError(
                "E_KG262_REPLAY_IDENTITY_REQUIRED", "replay_version is required"
            )
        if re.fullmatch(r"V[0-9]+\.[0-9]+(?:\.[0-9]+)?", replay_version) is None:
            raise GraphSecurityError(
                "E_KG262_REPLAY_VERSION_MISMATCH",
                "replay_version must use the canonical V<major>.<minor> identity",
            )
        _validate_hash(str(snapshot_sha256), "snapshot_sha256")
    elif replay_version is not None or snapshot_sha256 is not None:
        raise GraphSecurityError(
            "E_KG262_CURRENT_REPLAY_MIXED",
            "Current graph input cannot contain Replay identity",
        )

    trusted_root = _trusted_root(root)
    entry_path = _canonical_map_path(str(entry_map))
    _safe_file(trusted_root, entry_path)
    map_bytes = _safe_read_bytes(trusted_root, entry_path)
    if map_bytes is None:
        raise GraphSecurityError("E_KG262_ENTRY_MAP_MISSING", "entry map is unreadable")
    try:
        map_text = map_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GraphSecurityError(
            "E_KG262_ENTRY_MAP_ENCODING", "entry map must be UTF-8"
        ) from exc
    map_frontmatter, map_body, map_diagnostics = _frontmatter(map_text)
    map_identity_findings = _identity_component_findings(map_frontmatter)
    if map_identity_findings:
        raise GraphSecurityError(
            "E_KG262_IDENTITY_COMPONENT_INVALID",
            "entry map identity components must not contain reference "
            "delimiters, whitespace, or control characters",
        )
    entry_map_ref = _qualified_ref(map_frontmatter)
    if entry_map_ref is None:
        raise GraphSecurityError(
            "E_KG262_ENTRY_MAP_IDENTITY", "entry map requires an exact identity"
        )
    expected_lifecycle = "current" if graph_role == "current" else "archived"
    if _controlled_text(map_frontmatter.get("lifecycle")).lower() != expected_lifecycle:
        raise GraphSecurityError(
            "E_KG262_GRAPH_ROLE_MISMATCH",
            f"{graph_role} loader cannot compile this map lifecycle",
        )
    map_is_replay = _is_replay_namespace(map_frontmatter.get("namespace"))
    if (graph_role == "current" and map_is_replay) or (
        graph_role == "replay" and not map_is_replay
    ):
        raise GraphSecurityError(
            "E_KG262_GRAPH_ROLE_MISMATCH",
            f"{graph_role} loader cannot compile this map namespace",
        )
    if graph_role == "replay":
        map_replay_version = _replay_namespace_version(
            map_frontmatter.get("namespace")
        )
        if (
            map_replay_version is None
            or map_replay_version.casefold() != str(replay_version).casefold()
        ):
            raise GraphSecurityError(
                "E_KG262_REPLAY_VERSION_MISMATCH",
                "replay_version does not match the Replay map identity",
            )

    rows = _table_rows(map_body, "Members")
    observations: list[dict[str, Any]] = [
        _observation(item["rule_id"], entry_map_ref, item["detail"])
        for item in map_diagnostics
    ]
    graph_members: list[dict[str, Any]] = []
    parsed_by_path: dict[str, dict[str, Any]] = {}
    seen_rows: set[tuple[str, str, str, str]] = set()

    for row_index, row in enumerate(rows, start=1):
        map_ref = _strip_markup(row.get("member_ref", "")) or None
        map_ref_parts = _reference_parts(map_ref) if map_ref else None
        if map_ref_parts is not None:
            member_is_replay = _is_replay_namespace(
                map_ref_parts["namespace"]
            )
            member_ref_version = _replay_namespace_version(
                map_ref_parts["namespace"]
            )
            if graph_role == "current" and member_is_replay:
                raise GraphSecurityError(
                    "E_KG262_GRAPH_ROLE_MISMATCH",
                    "Current map cannot authorize a Replay member identity",
                )
            if graph_role == "replay" and (
                not member_is_replay
                or member_ref_version is None
                or member_ref_version.casefold()
                != str(replay_version).casefold()
            ):
                raise GraphSecurityError(
                    "E_KG262_REPLAY_VERSION_MISMATCH",
                    "replay_version does not match a Replay map member identity",
                )
        raw_path = _extract_link(row.get("path", ""))
        if raw_path is None:
            observations.append(
                _observation(
                    "unreadable_map_member",
                    map_ref or entry_map_ref,
                    {"row_ordinal": row_index, "reason": "missing_path"},
                )
            )
            graph_members.append(
                {
                    "canonical_path": "",
                    "qualified_ref": None,
                    "source_sha256": None,
                    "compile_state": "unreadable",
                }
            )
            continue
        canonical_path = _canonical_map_path(raw_path)
        row_lifecycle = _controlled_text(row.get("lifecycle")).lower()
        if row_lifecycle != expected_lifecycle:
            raise GraphSecurityError(
                "E_KG262_GRAPH_ROLE_MISMATCH",
                f"{graph_role} loader cannot compile member lifecycle {row_lifecycle!r}",
            )
        row_key = (
            map_ref or "",
            canonical_path,
            _strip_markup(row.get("member_kind", "")),
            _strip_markup(row.get("lifecycle", "")),
        )
        if row_key in seen_rows:
            observations.append(
                _observation(
                    "duplicate_map_member",
                    map_ref or entry_map_ref,
                    {"canonical_path": canonical_path, "row_ordinal": row_index},
                )
            )
        seen_rows.add(row_key)
        _safe_file(trusted_root, canonical_path)
        source_bytes = _safe_read_bytes(trusted_root, canonical_path)
        if source_bytes is None:
            observations.append(
                _observation(
                    "unreadable_map_member",
                    map_ref or entry_map_ref,
                    {"canonical_path": canonical_path, "reason": "not_a_file"},
                )
            )
            graph_members.append(
                {
                    "canonical_path": canonical_path,
                    "qualified_ref": None,
                    "source_sha256": None,
                    "compile_state": "unreadable",
                }
            )
            continue
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        try:
            text = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            observations.append(
                _observation(
                    "unreadable_map_member",
                    map_ref or entry_map_ref,
                    {"canonical_path": canonical_path, "reason": "invalid_utf8"},
                )
            )
            graph_members.append(
                {
                    "canonical_path": canonical_path,
                    "qualified_ref": None,
                    "source_sha256": source_sha256,
                    "compile_state": "partial",
                }
            )
            continue
        frontmatter, body, frontmatter_diagnostics = _frontmatter(text)
        identity_findings = _identity_component_findings(frontmatter)
        actual_ref = _qualified_ref(frontmatter)
        if (
            actual_ref is not None
            and _controlled_text(frontmatter.get("lifecycle")).lower()
            != expected_lifecycle
        ):
            raise GraphSecurityError(
                "E_KG262_GRAPH_ROLE_MISMATCH",
                f"{graph_role} loader cannot compile document lifecycle",
            )
        if actual_ref is not None:
            document_is_replay = _is_replay_namespace(frontmatter.get("namespace"))
            if (graph_role == "current" and document_is_replay) or (
                graph_role == "replay" and not document_is_replay
            ):
                raise GraphSecurityError(
                    "E_KG262_GRAPH_ROLE_MISMATCH",
                    f"{graph_role} loader cannot compile document namespace",
                )
            if graph_role == "replay":
                document_replay_version = _replay_namespace_version(
                    frontmatter.get("namespace")
                )
                if (
                    document_replay_version is None
                    or document_replay_version.casefold()
                    != str(replay_version).casefold()
                ):
                    raise GraphSecurityError(
                        "E_KG262_REPLAY_VERSION_MISMATCH",
                        "replay_version does not match a Replay document identity",
                    )
        for diagnostic in frontmatter_diagnostics:
            observations.append(
                _observation(
                    diagnostic["rule_id"],
                    actual_ref or map_ref or entry_map_ref,
                    {"canonical_path": canonical_path, **diagnostic["detail"]},
                )
            )
        for finding in identity_findings:
            observations.append(
                _observation(
                    "invalid_identity_component",
                    map_ref or entry_map_ref,
                    {"canonical_path": canonical_path, **finding},
                )
            )
        compile_state = "parsed"
        if actual_ref is None or actual_ref != map_ref:
            compile_state = "partial"
            observations.append(
                _observation(
                    "member_identity_mismatch",
                    map_ref or entry_map_ref,
                    {
                        "canonical_path": canonical_path,
                        "map_ref": map_ref,
                        "document_ref": actual_ref,
                    },
                )
            )
        graph_members.append(
            {
                "canonical_path": canonical_path,
                "qualified_ref": map_ref if actual_ref is not None else None,
                "source_sha256": source_sha256,
                "compile_state": compile_state,
            }
        )
        if canonical_path not in parsed_by_path:
            parsed_by_path[canonical_path] = {
                "map_ref": map_ref,
                "actual_ref": actual_ref,
                "frontmatter": frontmatter,
                "body": body,
                "compile_state": compile_state,
                "source_sha256": source_sha256,
            }

    graph_members.sort(
        key=lambda item: (
            item["canonical_path"].encode("utf-8"),
            (b"" if item["qualified_ref"] is None else item["qualified_ref"].encode("utf-8")),
            json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
        )
    )
    graph_input: dict[str, Any] = {
        "schema": GRAPH_INPUT_SCHEMA,
        "profile_id": PROFILE_ID,
        "profile_document_sha256": profile_document_sha256,
        "parser_contract_id": PARSER_CONTRACT_ID,
        "kg_base_iri": kg_base_iri,
        "graph_role": graph_role,
        "route_identity": route_identity,
        "entry_map_ref": entry_map_ref,
        "entry_map_sha256": hashlib.sha256(map_bytes).hexdigest(),
        "members": graph_members,
    }
    if graph_role == "replay":
        graph_input["replay_version"] = replay_version
        graph_input["snapshot_sha256"] = snapshot_sha256
    canonical_json = json.dumps(
        graph_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    graph_input_sha256 = hashlib.sha256(canonical_json).hexdigest()
    if graph_role == "current":
        graph_iri = kg_base_iri + "/graph/current/" + graph_input_sha256
    else:
        graph_iri = (
            kg_base_iri
            + "/graph/replay/"
            + pct_segment(str(replay_version))
            + "/"
            + graph_input_sha256
        )

    documents: dict[str, dict[str, Any]] = {}
    claims: dict[str, dict[str, Any]] = {}
    triples: set[Triple] = set()
    claims_by_path_and_id: dict[tuple[str, str], str] = {}
    revision_iri_owners: dict[str, tuple[str, str]] = {}
    claim_iri_owners: dict[str, str] = {}

    for canonical_path in sorted(parsed_by_path, key=lambda value: value.encode("utf-8")):
        parsed = parsed_by_path[canonical_path]
        # An identity mismatch is observable but not authorized as another identity.
        if parsed["compile_state"] != "parsed":
            continue
        frontmatter = parsed["frontmatter"]
        reference = str(parsed["actual_ref"])
        if reference in documents:
            observations.append(
                _observation(
                    "duplicate_document_revision_identity",
                    reference,
                    {
                        "selected_path": documents[reference]["path"],
                        "duplicate_path": canonical_path,
                        "selection": "first_canonical_path",
                    },
                )
            )
            continue
        if not _valid_timestamp(frontmatter.get("timestamp")):
            observations.append(
                _observation(
                    "invalid_timestamp",
                    reference,
                    {"value": frontmatter.get("timestamp")},
                )
            )
        controlled_metadata = {
            field: _controlled_text(frontmatter.get(field))
            for field in ("modality", "epistemic_state", "sensitivity")
        }
        missing_controlled_metadata = sorted(
            field for field, value in controlled_metadata.items() if not value
        )
        if missing_controlled_metadata:
            observations.append(
                _observation(
                    "missing_recommended_metadata",
                    reference,
                    {
                        "fields": missing_controlled_metadata,
                        "projection": "withheld",
                    },
                )
            )
        stable_iri, revision_iri = _document_iris(kg_base_iri, frontmatter)
        if revision_iri in revision_iri_owners:
            selected_ref, selected_path = revision_iri_owners[revision_iri]
            observations.append(
                _observation(
                    "identity_nfc_collision",
                    reference,
                    {
                        "selected_ref": selected_ref,
                        "selected_path": selected_path,
                        "collision_path": canonical_path,
                        "revision_iri": revision_iri,
                        "projection": "withheld",
                    },
                    severity="high",
                )
            )
            continue
        revision_iri_owners[revision_iri] = (reference, canonical_path)
        source_sha256 = str(parsed["source_sha256"])
        revision_digest = hashlib.sha256(
            json.dumps(
                {
                    "parser_contract_id": PARSER_CONTRACT_ID,
                    "qualified_ref": reference,
                    "source_sha256": source_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        aliases: list[str] = []
        for key in ("aliases_zh", "aliases_en"):
            value = frontmatter.get(key, [])
            if isinstance(value, list):
                aliases.extend(str(item) for item in value)
        document = {
            "reference": reference,
            "path": canonical_path,
            "stable_iri": stable_iri,
            "revision_iri": revision_iri,
            "type": str(frontmatter.get("type", "")),
            "title": str(frontmatter.get("title", "")),
            "description": str(frontmatter.get("description", "")),
            "timestamp": str(frontmatter.get("timestamp", "")),
            "namespace": str(frontmatter["namespace"]),
            "knowledge_id": str(frontmatter["knowledge_id"]),
            "revision": str(frontmatter["revision"]),
            "lifecycle": _controlled_text(frontmatter.get("lifecycle")).lower(),
            "modality": controlled_metadata["modality"],
            "epistemic_state": controlled_metadata["epistemic_state"],
            "sensitivity": controlled_metadata["sensitivity"],
            "aliases": aliases,
            "claim_refs": [],
            "source_sha256": source_sha256,
            "revision_digest": revision_digest,
            "source_anchor": canonical_path,
            "extraction_state": "parsed",
            "graph_iri": graph_iri,
            "graph_input_sha256": graph_input_sha256,
        }
        documents[reference] = document
        vocab = kg_base_iri + "/vocab/"
        triples.update(
            {
                _iri(stable_iri, RDF + "type", vocab + "KnowledgeResource"),
                _iri(stable_iri, RDF + "type", PROV + "Entity"),
                _literal(stable_iri, DCTERMS + "identifier", reference.rsplit("@", 1)[0]),
                _iri(revision_iri, RDF + "type", vocab + "KnowledgeRevision"),
                _iri(revision_iri, RDF + "type", PROV + "Entity"),
                _iri(revision_iri, DCTERMS + "isVersionOf", stable_iri),
                _iri(revision_iri, PROV + "specializationOf", stable_iri),
                _literal(revision_iri, DCTERMS + "identifier", reference),
                _literal(revision_iri, DCTERMS + "title", document["title"]),
                _literal(revision_iri, DCTERMS + "description", document["description"]),
                _literal(revision_iri, vocab + "revision", document["revision"]),
                _literal(revision_iri, vocab + "ownerText", str(frontmatter.get("owner", ""))),
                _iri(revision_iri, vocab + "lifecycle", vocab + pct_segment(document["lifecycle"])),
            }
        )
        for field, predicate_name in (
            ("modality", "modality"),
            ("epistemic_state", "epistemicState"),
            ("sensitivity", "sensitivity"),
        ):
            if document[field]:
                triples.add(
                    _iri(
                        revision_iri,
                        vocab + predicate_name,
                        vocab + pct_segment(document[field]),
                    )
                )
        controlled_type = _TYPE_NAMES.get(document["type"])
        if controlled_type:
            triples.add(_iri(revision_iri, RDF + "type", vocab + controlled_type))
        elif document["type"]:
            triples.add(_literal(revision_iri, vocab + "declaredType", document["type"]))
        if _valid_timestamp(document["timestamp"]):
            triples.add(
                _literal(
                    revision_iri,
                    DCTERMS + "modified",
                    document["timestamp"],
                    datatype=XSD + "dateTimeStamp",
                )
            )
        else:
            triples.add(_literal(revision_iri, vocab + "timestampText", document["timestamp"]))
        for alias in aliases:
            triples.add(_literal(revision_iri, DCTERMS + "alternative", alias))

        for claim_section in _claim_sections(parsed["body"]):
            claim_id = claim_section["claim_id"]
            if (
                not claim_id
                or "#" in claim_id
                or any(
                    character.isspace()
                    or ord(character) <= 0x1F
                    or ord(character) == 0x7F
                    for character in claim_id
                )
            ):
                observations.append(
                    _observation(
                        "invalid_claim_id",
                        reference,
                        {
                            "claim_id": claim_id,
                            "source_anchor": canonical_path + "#" + claim_id,
                            "projection": "withheld",
                        },
                    )
                )
                continue
            claim_ref = reference + "#" + claim_id
            stable_claim, occurrence = _claim_iris(kg_base_iri, frontmatter, claim_id)
            if claim_ref in claims:
                observations.append(
                    _observation(
                        "duplicate_claim_identity",
                        claim_ref,
                        {"source_anchor": canonical_path + "#" + claim_id},
                    )
                )
                continue
            if occurrence in claim_iri_owners:
                observations.append(
                    _observation(
                        "identity_nfc_collision",
                        claim_ref,
                        {
                            "selected_claim_ref": claim_iri_owners[occurrence],
                            "claim_occurrence_iri": occurrence,
                            "projection": "withheld",
                        },
                        severity="high",
                    )
                )
                continue
            claim_iri_owners[occurrence] = claim_ref
            claim = {
                "reference": claim_ref,
                "document_ref": reference,
                "document_path": canonical_path,
                "claim_id": claim_id,
                "claim_text": claim_section["claim_text"],
                "stable_iri": stable_claim,
                "occurrence_iri": occurrence,
                "evidence_paths": [],
                "evidence_refs": [],
                "relations": claim_section["relations"],
                "_evidence_links": list(claim_section["evidence_links"]),
                "source_sha256": source_sha256,
                "revision_digest": revision_digest,
                "source_anchor": canonical_path + "#" + claim_id,
                "extraction_state": "parsed",
                "graph_iri": graph_iri,
                "graph_input_sha256": graph_input_sha256,
            }
            claims[claim_ref] = claim
            claims_by_path_and_id[(canonical_path, claim_id)] = claim_ref
            document["claim_refs"].append(claim_ref)
            triples.update(
                {
                    _iri(stable_claim, RDF + "type", vocab + "Claim"),
                    _iri(stable_claim, RDF + "type", PROV + "Entity"),
                    _literal(
                        stable_claim,
                        DCTERMS + "identifier",
                        reference.rsplit("@", 1)[0] + "#" + claim_id,
                    ),
                    _iri(occurrence, RDF + "type", vocab + "ClaimOccurrence"),
                    _iri(occurrence, RDF + "type", PROV + "Entity"),
                    _iri(occurrence, DCTERMS + "isPartOf", revision_iri),
                    _iri(occurrence, PROV + "specializationOf", stable_claim),
                    _literal(occurrence, vocab + "claimText", claim_section["claim_text"]),
                }
            )

    for claim_ref in sorted(claims, key=lambda value: value.encode("utf-8")):
        claim = claims[claim_ref]
        for raw_link in claim.pop("_evidence_links"):
            linked_path, anchor = _body_link_identity(
                claim["document_path"], raw_link
            )
            evidence_ref = (
                claims_by_path_and_id.get((linked_path, anchor))
                if linked_path and anchor
                else None
            )
            if evidence_ref:
                if linked_path not in claim["evidence_paths"]:
                    claim["evidence_paths"].append(linked_path)
                if evidence_ref not in claim["evidence_refs"]:
                    claim["evidence_refs"].append(evidence_ref)
                triples.add(
                    _iri(
                        claim["occurrence_iri"],
                        DCTERMS + "references",
                        claims[evidence_ref]["occurrence_iri"],
                    )
                )
            else:
                observations.append(
                    _observation(
                        "dangling_or_mismatched_evidence",
                        claim_ref,
                        {
                            "evidence_path": linked_path,
                            "evidence_anchor": anchor,
                        },
                    )
                )

    edges: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    conflict_index: dict[tuple[str, str], set[str]] = {}
    relation_stable_owners: dict[
        tuple[str, str], tuple[str, str, str, str]
    ] = {}
    relation_occurrence_owners: dict[
        tuple[str, str, str, str, str], tuple[str, int]
    ] = {}

    for claim_ref in sorted(claims, key=lambda value: value.encode("utf-8")):
        claim = claims[claim_ref]
        source_parts = _reference_parts(claim_ref)
        if source_parts is None:
            observations.append(
                _observation(
                    "invalid_claim_id",
                    claim_ref,
                    {"projection": "withheld"},
                )
            )
            continue
        for row_ordinal, row in enumerate(claim.pop("relations"), start=1):
            relation_id = _strip_markup(row.get("relation_id", ""))
            predicate_name = _strip_markup(row.get("predicate", "")).upper()
            target_ref = _strip_markup(row.get("target_ref", ""))
            if relation_id:
                relation_key = (
                    pct_segment(str(source_parts["namespace"])),
                    pct_segment(relation_id),
                )
                source_lineage = (
                    str(source_parts["knowledge_id"]),
                    str(source_parts["claim_id"]),
                )
                if relation_key in relation_stable_owners:
                    first_raw_id, first_knowledge, first_claim_id, first_claim = (
                        relation_stable_owners[relation_key]
                    )
                    if first_raw_id != relation_id:
                        rule_id = "identity_nfc_collision"
                    elif (first_knowledge, first_claim_id) != source_lineage:
                        rule_id = "relation_identity_drift"
                    else:
                        rule_id = None
                    if rule_id is not None:
                        observations.append(
                            _observation(
                                rule_id,
                                claim_ref,
                                {
                                    "relation_id": relation_id,
                                    "selected_relation_id": first_raw_id,
                                    "selected_claim_ref": first_claim,
                                    "projection": "withheld",
                                },
                                severity="high",
                            )
                        )
                        continue
                else:
                    relation_stable_owners[relation_key] = (
                        relation_id,
                        source_lineage[0],
                        source_lineage[1],
                        claim_ref,
                    )
                occurrence_key = (
                    relation_key[0],
                    relation_key[1],
                    str(source_parts["knowledge_id"]),
                    str(source_parts["revision"]),
                    str(source_parts["claim_id"]),
                )
                if occurrence_key in relation_occurrence_owners:
                    first_claim, first_row = relation_occurrence_owners[
                        occurrence_key
                    ]
                    observations.append(
                        _observation(
                            "duplicate_relation_id",
                            claim_ref,
                            {
                                "relation_id": relation_id,
                                "selected_claim_ref": first_claim,
                                "selected_row_ordinal": first_row,
                                "duplicate_row_ordinal": row_ordinal,
                                "selection": "first_occurrence",
                            },
                            severity="high",
                        )
                    )
                    continue
                relation_occurrence_owners[occurrence_key] = (
                    claim_ref,
                    row_ordinal,
                )

            raw_assertion_state = _strip_markup(
                row.get("assertion_state", "")
            ).lower()
            if "assertion_state" not in row:
                observations.append(
                    _observation(
                        "missing_assertion_state_column",
                        claim_ref,
                        {
                            "relation_id": relation_id or None,
                            "row_ordinal": row_ordinal,
                            "projection": "withheld",
                        },
                    )
                )
                continue
            if "assertion_state" in row and not raw_assertion_state:
                observations.append(
                    _observation(
                        "missing_assertion_state",
                        claim_ref,
                        {
                            "relation_id": relation_id or None,
                            "row_ordinal": row_ordinal,
                            "projection": "withheld",
                        },
                    )
                )
                continue
            if raw_assertion_state in {"asserted", "described"}:
                assertion_state = raw_assertion_state
            else:
                assertion_state = "described"
                observations.append(
                    _observation(
                        "unknown_assertion_state",
                        claim_ref,
                        {
                            "relation_id": relation_id or None,
                            "value": raw_assertion_state,
                            "projection": "described",
                        },
                    )
                )
            target = claims.get(target_ref)
            predicate = _predicate_iri(kg_base_iri, predicate_name)
            raw_target_link = _extract_link(row.get("target", ""))
            target_link_path, target_link_anchor = (
                _body_link_identity(claim["document_path"], raw_target_link)
                if raw_target_link
                else (None, None)
            )
            target_matches = bool(
                target
                and target_link_path
                and target_link_path == target["document_path"]
                and target_link_anchor == target["claim_id"]
            )
            if not target or not predicate or not target_matches:
                observations.append(
                    _observation(
                        "dangling_or_mismatched_target",
                        claim_ref,
                        {
                            "relation_id": relation_id or None,
                            "target_ref": target_ref or None,
                            "target_path": target_link_path,
                            "target_anchor": target_link_anchor,
                            "predicate": predicate_name or None,
                        },
                    )
                )
                continue

            source_evidence_ref: str | None = None
            source_evidence_path: str | None = None
            raw_source_link = _extract_link(row.get("source_ref", ""))
            if raw_source_link:
                source_evidence_path, anchor = _body_link_identity(
                    claim["document_path"], raw_source_link
                )
                if source_evidence_path and anchor:
                    source_evidence_ref = claims_by_path_and_id.get(
                        (source_evidence_path, anchor)
                    )
            if source_evidence_ref:
                if source_evidence_path not in claim["evidence_paths"]:
                    claim["evidence_paths"].append(source_evidence_path)
                if source_evidence_ref not in claim["evidence_refs"]:
                    claim["evidence_refs"].append(source_evidence_ref)
            if raw_source_link and not source_evidence_ref:
                observations.append(
                    _observation(
                        "dangling_or_mismatched_evidence",
                        claim_ref,
                        {
                            "relation_id": relation_id or None,
                            "evidence_path": source_evidence_path,
                            "evidence_anchor": anchor if raw_source_link else None,
                        },
                    )
                )

            stable_relation = None
            if relation_id:
                stable_relation = (
                    kg_base_iri
                    + "/relation/"
                    + pct_segment(str(source_parts["namespace"]))
                    + "/"
                    + pct_segment(relation_id)
                )
                occurrence = (
                    kg_base_iri
                    + "/statement/"
                    + pct_segment(str(source_parts["namespace"]))
                    + "/"
                    + pct_segment(relation_id)
                    + "/source/"
                    + pct_segment(str(source_parts["knowledge_id"]))
                    + "/"
                    + pct_segment(str(source_parts["revision"]))
                    + "/"
                    + pct_segment(str(source_parts["claim_id"]))
                )
            else:
                occurrence = (
                    kg_base_iri
                    + "/statement-occurrence/"
                    + pct_segment(str(source_parts["namespace"]))
                    + "/"
                    + pct_segment(str(source_parts["knowledge_id"]))
                    + "/"
                    + pct_segment(str(source_parts["revision"]))
                    + "/"
                    + pct_segment(str(source_parts["claim_id"]))
                    + "/row/"
                    + str(row_ordinal)
                )
            statement = {
                "iri": occurrence,
                "subject": claim["occurrence_iri"],
                "predicate": predicate,
                "object": target["occurrence_iri"],
                "occurrence_of": stable_relation,
                "relation_id": relation_id or None,
                "assertion_state": assertion_state,
                "qualifier": _strip_markup(row.get("qualifier", "")),
                "source_ref": source_evidence_ref,
                "source_path": source_evidence_path,
            }
            statements.append(statement)
            triples.update(
                {
                    _iri(occurrence, RDF + "type", RDF + "Statement"),
                    _iri(occurrence, RDF + "type", PROV + "Entity"),
                    _iri(occurrence, RDF + "subject", claim["occurrence_iri"]),
                    _iri(occurrence, RDF + "predicate", predicate),
                    _iri(occurrence, RDF + "object", target["occurrence_iri"]),
                    _literal(
                        occurrence,
                        kg_base_iri + "/vocab/assertionState",
                        assertion_state,
                    ),
                    _literal(
                        occurrence,
                        kg_base_iri + "/vocab/qualifier",
                        statement["qualifier"],
                    ),
                }
            )
            if stable_relation:
                triples.update(
                    {
                        _iri(
                            stable_relation,
                            RDF + "type",
                            kg_base_iri + "/vocab/RelationAssertion",
                        ),
                        _literal(stable_relation, DCTERMS + "identifier", relation_id),
                        _iri(
                            occurrence,
                            kg_base_iri + "/vocab/occurrenceOf",
                            stable_relation,
                        ),
                    }
                )
            if source_evidence_ref:
                triples.add(
                    _iri(
                        occurrence,
                        DCTERMS + "references",
                        claims[source_evidence_ref]["occurrence_iri"],
                    )
                )
            if assertion_state == "asserted":
                direct = _iri(
                    claim["occurrence_iri"], predicate, target["occurrence_iri"]
                )
                triples.add(direct)
                edge = {
                    "result_kind": "edge",
                    "statement_iri": occurrence,
                    "subject": direct.subject,
                    "subject_ref": claim_ref,
                    "predicate": direct.predicate,
                    "predicate_name": predicate_name,
                    "object": direct.object,
                    "object_ref": target_ref,
                    "relation_id": relation_id or None,
                    "source_ref": claim_ref,
                    "source_path": claim["document_path"],
                    "source_sha256": claim["source_sha256"],
                    "revision_digest": claim["revision_digest"],
                    "evidence_ref": source_evidence_ref,
                    "evidence_path": source_evidence_path,
                }
                if edge not in edges:
                    edges.append(edge)
                conflict_index.setdefault(
                    (claim["occurrence_iri"], target["occurrence_iri"]), set()
                ).add(predicate_name)

    for (subject, target), predicates in sorted(conflict_index.items()):
        if {"SUPPORTS", "REFUTES"}.issubset(predicates):
            observations.append(
                _observation(
                    "conflict_candidate",
                    next(
                        reference
                        for reference, item in claims.items()
                        if item["occurrence_iri"] == subject
                    ),
                    {
                        "target_ref": next(
                            reference
                            for reference, item in claims.items()
                            if item["occurrence_iri"] == target
                        ),
                        "predicates": ["REFUTES", "SUPPORTS"],
                    },
                    severity="high",
                )
            )

    # Evidence references were resolved by exact path + claim anchor above.
    # Sorting here cannot manufacture a path-level fallback identity.
    for claim in claims.values():
        claim["evidence_paths"] = sorted(
            set(claim["evidence_paths"]), key=lambda value: value.encode("utf-8")
        )
        claim["evidence_refs"] = sorted(
            set(claim["evidence_refs"]), key=lambda value: value.encode("utf-8")
        )

    for observation in observations:
        observation["graph_iri"] = graph_iri
        observation["graph_input_sha256"] = graph_input_sha256
        observation["route_identity"] = route_identity

    observations.sort(
        key=lambda item: (
            item["rule_id"].encode("utf-8"),
            item["subject_ref"].encode("utf-8"),
            item["finding_id"].encode("utf-8"),
        )
    )
    statements.sort(key=lambda item: item["iri"].encode("utf-8"))
    edges.sort(
        key=lambda item: (
            item["subject"].encode("utf-8"),
            item["predicate"].encode("utf-8"),
            item["object"].encode("utf-8"),
        )
    )
    documents = dict(
        sorted(documents.items(), key=lambda item: item[0].encode("utf-8"))
    )
    claims = dict(sorted(claims.items(), key=lambda item: item[0].encode("utf-8")))
    return DocumentGraph(
        graph_role=graph_role,
        route_identity=route_identity,
        acceptance_eligible=graph_role == "current",
        graph_input=graph_input,
        graph_input_sha256=graph_input_sha256,
        graph_iri=graph_iri,
        kg_base_iri=kg_base_iri,
        member_paths=tuple(
            sorted(parsed_by_path, key=lambda value: value.encode("utf-8"))
        ),
        documents=documents,
        claims=claims,
        triples=tuple(sorted(triples)),
        statements=tuple(statements),
        observations=tuple(observations),
        edges=tuple(edges),
    )


def load_current_graph(
    root: Path | str,
    entry_map: str,
    *,
    kg_base_iri: str,
    route_identity: str,
    profile_document_sha256: str,
) -> DocumentGraph:
    """Compile the exact trusted Current map closure into a fresh graph."""

    return _compile_graph(
        root,
        entry_map,
        graph_role="current",
        kg_base_iri=kg_base_iri,
        route_identity=route_identity,
        profile_document_sha256=profile_document_sha256,
    )


def load_replay_graph(
    root: Path | str,
    entry_map: str,
    *,
    kg_base_iri: str,
    route_identity: str,
    profile_document_sha256: str,
    replay_version: str,
    snapshot_sha256: str,
) -> DocumentGraph:
    """Compile one explicitly identified Replay map into an ineligible graph."""

    return _compile_graph(
        root,
        entry_map,
        graph_role="replay",
        kg_base_iri=kg_base_iri,
        route_identity=route_identity,
        profile_document_sha256=profile_document_sha256,
        replay_version=replay_version,
        snapshot_sha256=snapshot_sha256,
    )


__all__ = [
    "GraphSecurityError",
    "load_current_graph",
    "load_replay_graph",
    "normalize_nfc17",
    "pct_segment",
]
