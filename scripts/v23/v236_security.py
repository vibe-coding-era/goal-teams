#!/usr/bin/env python3
"""Shared Goal Teams secret detection and deterministic redaction.

The module is intentionally dependency-free so the V2.3 core validator and
the V2.34/V2.36 archive adapters use exactly the same security boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "aws_access_key_id",
        "aws_secret_access_key",
        "code",
        "credential",
        "client_secret",
        "key",
        "password",
        "secret",
        "signature",
        "sig",
        "token",
    }
)

SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "access_key",
        "access_key_id",
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "client_secret",
        "client_key_data",
        "cookie",
        "credential",
        "password",
        "passwd",
        "private_key",
        "private_key_data",
        "pwd",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "service_account_key_data",
        "sig",
        "signature",
        "token",
        "tls_key",
    }
)
SENSITIVE_CONFIG_SUFFIXES = (
    "_access_key",
    "_access_key_id",
    "_access_token",
    "_api_key",
    "_apikey",
    "_auth_token",
    "_client_secret",
    "_cookie",
    "_credential",
    "_password",
    "_passwd",
    "_private_key",
    "_pwd",
    "_refresh_token",
    "_secret",
    "_secret_key",
    "_session_token",
    "_signature",
    "_token",
)
NON_SECRET_CONFIG_KEYS = frozenset(
    {
        "continuation_token",
        "next_page_token",
        "page_token",
        "pagination_token",
    }
)

PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----"
    r".*?-----END (?P=label)-----",
    re.IGNORECASE | re.DOTALL,
)
AUTH_HEADER_RE = re.compile(
    r"(?im)^(?P<header>authorization|proxy-authorization|cookie|set-cookie|x-api-key)"
    r"\s*:\s*(?:(?P<scheme>[A-Za-z][A-Za-z0-9_-]*)\s+)?(?P<value>[^\r\n]+)$"
)
JSON_PAIR_RE = re.compile(
    r'(?P<prefix>"(?P<key>(?:[^"\\]|\\.)+)"\s*:\s*)'
    r'(?P<value>"(?:[^"\\]|\\.)*"|[^,{}\r\n]+)'
)
INLINE_ASSIGNMENT_RE = re.compile(
    # URL query pairs are handled by URL_RE so pagination parameters such as
    # page_token are not mistaken for standalone credential assignments.
    r"(?i)(?<![A-Za-z0-9_.?&-])"
    r"(?P<key_quote>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=key_quote)"
    r"(?P<separator>\s*=\s*)"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'[^']*'|\{\{[^{}\r\n]+\}\}|[^\s&;,]+)"
)
YAML_ASSIGNMENT_RE = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:-[ \t]+)?)"
    r"(?P<key_quote>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=key_quote)"
    r"(?P<separator>[ \t]*:[ \t]*)(?P<value>[^\r\n]*)$"
)
YAML_BLOCK_HEADER_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:-[ \t]+)?)"
    r"(?P<key_quote>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=key_quote)"
    r"(?P<separator>[ \t]*:[ \t]*)"
    r"(?P<indicator>[|>](?:[1-9][+-]?|[+-][1-9]?)?)"
    r"(?P<suffix>[ \t]*(?:#.*)?)$"
)
TOML_MULTILINE_HEADER_RE = re.compile(
    r"^(?P<prefix>[ \t]*)"
    r"(?P<key_quote>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=key_quote)"
    r"(?P<separator>[ \t]*=[ \t]*)"
    r"(?P<delimiter>\"\"\"|''')(?P<rest>.*)$"
)
NETRC_STANDALONE_RE = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:password|passwd)[ \t]+)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|(?![=:])[^\s#;]+)"
    r"(?P<suffix>[^\r\n]*)$"
)
NETRC_MACHINE_RE = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:machine[ \t]+\S+|default)\b[^\r\n]*?"
    r"\b(?:password|passwd)[ \t]+)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s#;]+)"
    r"(?P<suffix>[^\r\n]*)$"
)
BEARER_RE = re.compile(
    r"(?i)(?P<prefix>\bbearer\s+)(?P<value>[A-Za-z0-9._~+/-]{8,}={0,2})"
)
CLI_LONG_OPTION_RE = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r"(?P<option>--(?P<key>[A-Za-z][A-Za-z0-9_-]*))"
    r"(?:"
    r"(?P<equals>[ \t]*=[ \t]*)(?P<equals_value>"
    r"\"(?:[^\"\\]|\\.)*\"|'[^'\r\n]*'|\{\{[^{}\r\n]+\}\}|[^\s;&|]+)"
    r"|"
    r"(?P<spaces>[ \t]+)(?P<spaces_value>"
    r"\"(?:[^\"\\]|\\.)*\"|'[^'\r\n]*'|\{\{[^{}\r\n]+\}\}|(?!-)[^\s;&|]+)"
    r")"
)
CLI_USERINFO_RE = re.compile(
    r"(?ix)(?<!\S)"
    r"(?P<option>--(?:proxy-)?user(?:[ \t]*=[ \t]*|[ \t]+)|-u[ \t]*)"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'[^'\r\n]*'|[^\s;&|]+)"
)
COMMON_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"SG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{40,}|"
    r"pypi-[A-Za-z0-9_-]{40,}|"
    r"sk-[A-Za-z0-9_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"AIza[A-Za-z0-9_-]{30,}|"
    r"(?:sk|rk)_live_[A-Za-z0-9]{16,}|"
    r"npm_[A-Za-z0-9]{30,}|"
    r"ya29\.[A-Za-z0-9_-]{20,}|"
    r"dop_v1_[A-Za-z0-9]{32,}|"
    r"hf_[A-Za-z0-9]{24,}|"
    r"(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA|A3T)[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")(?![A-Za-z0-9])"
)
TOKEN_LIKE_URL_USERNAME_RE = re.compile(
    r"(?i)(?:"
    r"(?:access[-_.]?token|api[-_.]?key|apikey|bearer|oauth2?|pat|"
    r"personal[-_.]?access[-_.]?token|token)"
    r"[-_.][A-Za-z0-9._~+/-]{8,}={0,2}"
    r")"
)
URL_RE = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^\s<>\"']+")
HOME_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:"
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|"
    r"/Users" r"/[^/\s]+|"
    r"/home" r"/[^/\s]+|"
    r"/ro" r"ot|"
    r"/var/ro" r"ot"
    r")(?=/|\\|\b)",
    re.IGNORECASE,
)


def _redaction_marker(secret: str, hmac_key: str | bytes | None) -> str:
    if hmac_key is None:
        return "[REDACTED]"
    key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
    correlation = hmac.new(key, secret.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"[REDACTED:{correlation}]"


def _already_redacted(value: str) -> bool:
    decoded = unquote(value)
    return re.fullmatch(r"\[REDACTED(?::[0-9a-f]{16})?\]", decoded) is not None


def _normalized_key(value: str) -> str:
    expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", expanded)
    return re.sub(r"[^a-z0-9]+", "_", expanded.lower()).strip("_")


def _sensitive_config_key(value: str) -> bool:
    normalized = _normalized_key(value)
    if normalized in NON_SECRET_CONFIG_KEYS:
        return False
    return normalized in SENSITIVE_CONFIG_KEYS or normalized.endswith(
        SENSITIVE_CONFIG_SUFFIXES
    )


def _sensitive_query_key(value: str) -> bool:
    return _normalized_key(value) in SENSITIVE_QUERY_KEYS


def _sensitive_cli_key(value: str) -> bool:
    """Recognize credential-bearing long options without treating IDs as secrets."""
    normalized = _normalized_key(value)
    if normalized in NON_SECRET_CONFIG_KEYS:
        return False
    if normalized in {
        "access_key",
        "access_key_id",
        "access_token",
        "api_key",
        "apikey",
        "api_token",
        "auth_token",
        "authorization",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "bearer_token",
        "client_key_data",
        "client_secret",
        "cookie",
        "credential",
        "oauth2_bearer",
        "password",
        "passwd",
        "personal_access_token",
        "private_key",
        "private_key_data",
        "pwd",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "signature",
        "tls_key",
        "token",
    }:
        return True
    return normalized.endswith(
        (
            "_access_key",
            "_access_token",
            "_api_key",
            "_api_token",
            "_auth_token",
            "_client_secret",
            "_credential",
            "_password",
            "_private_key",
            "_refresh_token",
            "_secret",
            "_secret_key",
            "_session_token",
        )
    )


def _safe_reference(value: str) -> bool:
    """Recognize explicit masks and indirections that contain no credential."""
    stripped = unquote(value).strip()
    if len(stripped) >= 2 and stripped[0] in {'"', "'"} and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1].strip()
    if not stripped:
        return True
    if _already_redacted(stripped):
        return True
    if re.fullmatch(r"(?i)(?:null|none|nil|true|false|unset|not[_ -]?set|<redacted>)", stripped):
        return True
    return bool(
        re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", stripped)
        or re.fullmatch(r"\$\{[^{}]+\}", stripped)
        or re.fullmatch(r"\{\{\s*(?:secrets?|env|vault)\.[^{}]+\s*\}\}", stripped, re.IGNORECASE)
        or re.fullmatch(r"(?i)(?:env|secret|vault)://[^\s]+", stripped)
        or re.fullmatch(r"(?i)(?:os\.)?getenv\([^\r\n]+\)", stripped)
        or re.fullmatch(r"(?i)(?:os\.environ|env)\[[^\r\n]+\]", stripped)
    )


def _quoted_secret(raw: str) -> tuple[str, str, str]:
    """Return quote, decoded-ish secret, and closing quote for one scalar."""
    if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0]:
        if raw[0] == '"':
            try:
                return '"', str(json.loads(raw)), '"'
            except json.JSONDecodeError:
                pass
        return raw[0], raw[1:-1], raw[-1]
    return "", raw, ""


def _redact_header(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    header = match.group("header")
    scheme = match.group("scheme")
    value = match.group("value")
    if header.lower() in {"cookie", "set-cookie"}:
        redacted_parts: list[str] = []
        for part in value.split(";"):
            if "=" in part:
                key, secret = part.split("=", 1)
                if _safe_reference(secret):
                    redacted_parts.append(part.strip())
                else:
                    redacted_parts.append(
                        f"{key.strip()}={_redaction_marker(secret.strip(), hmac_key)}"
                    )
            else:
                redacted_parts.append(
                    part.strip()
                    if _safe_reference(part)
                    else _redaction_marker(part.strip(), hmac_key)
                )
        return f"{header}: " + "; ".join(redacted_parts)
    prefix = f"{header}: " + (f"{scheme} " if scheme else "")
    return prefix + (
        value.strip()
        if _safe_reference(value)
        else _redaction_marker(value.strip(), hmac_key)
    )


def _redact_inline_assignment(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    if not _sensitive_config_key(match.group("key")):
        return match.group(0)
    raw = match.group("value")
    quote_start, secret, quote_end = _quoted_secret(raw)
    if _safe_reference(secret):
        return match.group(0)
    marker = _redaction_marker(secret, hmac_key)
    return (
        f"{match.group('key_quote')}{match.group('key')}{match.group('key_quote')}"
        f"{match.group('separator')}"
        f"{quote_start}{marker}{quote_end}"
    )


def _redact_cli_long_option(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    if not _sensitive_cli_key(match.group("key")):
        return match.group(0)
    separator = match.group("equals") or match.group("spaces")
    raw = match.group("equals_value") or match.group("spaces_value")
    quote_start, secret, quote_end = _quoted_secret(raw)
    if _safe_reference(secret):
        return match.group(0)
    return (
        match.group("option")
        + separator
        + quote_start
        + _redaction_marker(secret, hmac_key)
        + quote_end
    )


def _redact_cli_userinfo(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    raw = match.group("value")
    quote_start, userinfo, quote_end = _quoted_secret(raw)
    if ":" not in userinfo:
        return match.group(0)
    username, password = userinfo.split(":", 1)
    if _safe_reference(password):
        return match.group(0)
    return (
        match.group("option")
        + quote_start
        + username
        + ":"
        + _redaction_marker(password, hmac_key)
        + quote_end
    )


def _redact_json_pair(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    try:
        key = json.loads('"' + match.group("key") + '"')
    except json.JSONDecodeError:
        key = match.group("key")
    if not _sensitive_config_key(str(key)):
        return match.group(0)
    raw = match.group("value").strip()
    quote_start, secret, _ = _quoted_secret(raw)
    if _safe_reference(secret):
        return match.group(0)
    if quote_start:
        return match.group("prefix") + json.dumps(_redaction_marker(secret, hmac_key))
    return match.group("prefix") + json.dumps(_redaction_marker(raw, hmac_key))


def _split_yaml_scalar(raw: str) -> tuple[str, str, str, str]:
    leading = raw[: len(raw) - len(raw.lstrip())]
    body = raw.strip()
    suffix = raw[len(raw.rstrip()) :]
    if not body:
        return leading, "", "", suffix
    if body[0] in {'"', "'"}:
        quote_char = body[0]
        escaped = False
        for index in range(1, len(body)):
            char = body[index]
            if quote_char == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote_char and not escaped:
                return leading, body[: index + 1], body[index + 1 :] + suffix, ""
            escaped = False
    comment = re.search(r"[ \t]+[#;].*$", body)
    if comment:
        return leading, body[: comment.start()], body[comment.start() :] + suffix, ""
    return leading, body, suffix, ""


def _redact_yaml_assignment(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    # Double-quoted keys have already passed through JSON_PAIR_RE.  Replaying
    # them as YAML would turn safe JSON scalars such as `"auth": false,` into
    # false positives because the JSON comma is part of the YAML scalar.
    if match.group("key_quote") == '"':
        return match.group(0)
    normalized = _normalized_key(match.group("key"))
    # Header syntax is handled first by AUTH_HEADER_RE.  Do not reinterpret a
    # sanitized header as a YAML scalar on the next pass.
    if normalized in {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "x_api_key",
    }:
        return match.group(0)
    if not _sensitive_config_key(match.group("key")):
        return match.group(0)
    leading, raw_scalar, trailing, extra = _split_yaml_scalar(match.group("value"))
    quote_start, secret, quote_end = _quoted_secret(raw_scalar)
    if _safe_reference(secret):
        return match.group(0)
    marker = _redaction_marker(secret, hmac_key)
    key_quote = match.group("key_quote")
    return (
        f"{match.group('prefix')}{key_quote}{match.group('key')}{key_quote}"
        f"{match.group('separator')}"
        f"{leading}{quote_start}{marker}{quote_end}{trailing}{extra}"
    )


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\r", "\n")):
        return line[:-1], line[-1]
    return line, ""


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _toml_multiline_close(value: str, delimiter: str) -> int:
    """Return the first non-escaped TOML multiline delimiter."""

    cursor = 0
    while True:
        index = value.find(delimiter, cursor)
        if index < 0:
            return -1
        if delimiter == "'''":
            return index
        backslashes = 0
        probe = index - 1
        while probe >= 0 and value[probe] == "\\":
            backslashes += 1
            probe -= 1
        if backslashes % 2 == 0:
            return index
        cursor = index + 1


def _redact_sensitive_multiline_scalars(
    text: str, hmac_key: str | bytes | None
) -> str:
    """Redact complete YAML block and TOML multiline credential values.

    Line-oriented scalar matchers can only see the ``|``/``>`` or triple-quote
    opener.  Replacing just that opener leaves the actual secret body public and
    makes the second detector pass incorrectly report a clean result.  This
    pre-pass consumes the whole scalar before any single-line redaction runs.
    """

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        body, ending = _split_line_ending(lines[index])
        yaml_header = YAML_BLOCK_HEADER_RE.fullmatch(body)
        if yaml_header is not None and _sensitive_config_key(yaml_header.group("key")):
            base_indent = _indent_width(yaml_header.group("prefix"))
            first_content = index + 1
            while first_content < len(lines):
                candidate, _candidate_ending = _split_line_ending(lines[first_content])
                if candidate.strip():
                    break
                first_content += 1
            if (
                first_content < len(lines)
                and _indent_width(_split_line_ending(lines[first_content])[0])
                > base_indent
            ):
                content_indent = _indent_width(
                    _split_line_ending(lines[first_content])[0]
                )
                end = first_content + 1
                while end < len(lines):
                    candidate, _candidate_ending = _split_line_ending(lines[end])
                    if candidate.strip() and _indent_width(candidate) < content_indent:
                        break
                    end += 1
                secret = "".join(lines[index + 1 : end])
                if not _safe_reference(secret.strip()):
                    marker = _redaction_marker(secret, hmac_key)
                    key_quote = yaml_header.group("key_quote")
                    output.append(
                        f"{yaml_header.group('prefix')}{key_quote}"
                        f"{yaml_header.group('key')}{key_quote}"
                        f"{yaml_header.group('separator')}{marker}"
                        f"{yaml_header.group('suffix')}{ending}"
                    )
                    index = end
                    continue

        toml_header = TOML_MULTILINE_HEADER_RE.fullmatch(body)
        if toml_header is not None and _sensitive_config_key(toml_header.group("key")):
            delimiter = toml_header.group("delimiter")
            rest = toml_header.group("rest")
            close = _toml_multiline_close(rest, delimiter)
            end = index + 1
            suffix = ""
            close_ending = ending
            secret_parts: list[str] = []
            if close >= 0:
                secret_parts.append(rest[:close])
                suffix = rest[close + len(delimiter) :]
            else:
                secret_parts.append(rest + ending)
                while end < len(lines):
                    candidate, candidate_ending = _split_line_ending(lines[end])
                    close = _toml_multiline_close(candidate, delimiter)
                    if close >= 0:
                        secret_parts.append(candidate[:close])
                        suffix = candidate[close + len(delimiter) :]
                        close_ending = candidate_ending
                        end += 1
                        break
                    secret_parts.append(lines[end])
                    end += 1
            secret = "".join(secret_parts)
            if not _safe_reference(secret.strip()):
                marker = _redaction_marker(secret, hmac_key)
                key_quote = toml_header.group("key_quote")
                output.append(
                    f"{toml_header.group('prefix')}{key_quote}"
                    f"{toml_header.group('key')}{key_quote}"
                    f"{toml_header.group('separator')}"
                    f"{json.dumps(marker)}{suffix}{close_ending}"
                )
                index = end
                continue

        output.append(lines[index])
        index += 1
    return "".join(output)


def _redact_netrc(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    raw = match.group("value")
    quote_start, secret, quote_end = _quoted_secret(raw)
    if _safe_reference(secret):
        return match.group(0)
    return (
        match.group("prefix")
        + quote_start
        + _redaction_marker(secret, hmac_key)
        + quote_end
        + match.group("suffix")
    )


def _redact_url(match: re.Match[str], hmac_key: str | bytes | None) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,);]}":
        if raw[-1] == "]" and re.search(
            r"\[REDACTED(?::[0-9a-f]{16})?\]$", raw
        ):
            break
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parts = urlsplit(raw)
    except ValueError:
        return _redaction_marker(raw, hmac_key) + trailing

    netloc = parts.netloc
    changed = False
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if ":" in userinfo:
            username, password = userinfo.split(":", 1)
            if not _safe_reference(password):
                marker = _redaction_marker(unquote(password), hmac_key)
                userinfo = f"{username}:{quote(marker, safe='')}"
                changed = True
        else:
            decoded_username = unquote(userinfo)
            if (
                not _safe_reference(decoded_username)
                and TOKEN_LIKE_URL_USERNAME_RE.fullmatch(decoded_username)
            ):
                userinfo = quote(
                    _redaction_marker(decoded_username, hmac_key), safe=""
                )
                changed = True
        netloc = f"{userinfo}@{host}"

    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _sensitive_query_key(key):
            if _safe_reference(value):
                pairs.append((key, value))
            else:
                pairs.append((key, _redaction_marker(value, hmac_key)))
                changed = True
        else:
            pairs.append((key, value))
    if not changed:
        return raw + trailing
    query = urlencode(pairs, safe="[]:")
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment)) + trailing


def redact_text(
    text: str,
    hmac_key: str | bytes | None = None,
    *,
    redact_home_paths: bool = True,
) -> str:
    """Return text with supported credentials replaced by stable markers."""
    key = hmac_key if hmac_key is not None else os.environ.get(
        "GOAL_TEAMS_REDACTION_HMAC_KEY"
    )
    redacted = _redact_sensitive_multiline_scalars(text, key)
    redacted = PRIVATE_KEY_RE.sub(
        lambda match: _redaction_marker(match.group(0), key), redacted
    )
    redacted = AUTH_HEADER_RE.sub(lambda match: _redact_header(match, key), redacted)
    redacted = JSON_PAIR_RE.sub(lambda match: _redact_json_pair(match, key), redacted)
    redacted = YAML_ASSIGNMENT_RE.sub(lambda match: _redact_yaml_assignment(match, key), redacted)
    redacted = INLINE_ASSIGNMENT_RE.sub(
        lambda match: _redact_inline_assignment(match, key), redacted
    )
    redacted = CLI_USERINFO_RE.sub(
        lambda match: _redact_cli_userinfo(match, key), redacted
    )
    redacted = CLI_LONG_OPTION_RE.sub(
        lambda match: _redact_cli_long_option(match, key), redacted
    )
    redacted = NETRC_MACHINE_RE.sub(lambda match: _redact_netrc(match, key), redacted)
    redacted = NETRC_STANDALONE_RE.sub(lambda match: _redact_netrc(match, key), redacted)
    redacted = BEARER_RE.sub(
        lambda match: match.group("prefix") + _redaction_marker(match.group("value"), key),
        redacted,
    )
    redacted = COMMON_TOKEN_RE.sub(
        lambda match: _redaction_marker(match.group(0), key), redacted
    )
    redacted = URL_RE.sub(lambda match: _redact_url(match, key), redacted)
    if redact_home_paths:
        redacted = HOME_PATH_RE.sub("~", redacted)
    return redacted


def contains_secret(text: str) -> bool:
    """Return true when shared redaction would remove credential material."""
    return redact_text(text, hmac_key=None, redact_home_paths=False) != text
