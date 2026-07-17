"""V2.36 shared secret redaction and public archive negative tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT, gt
from tests.v23.test_v234_state_loop import require_v234


def load_security():
    path = ROOT / "scripts/v23/v236_security.py"
    spec = importlib.util.spec_from_file_location("goalteams_v236_security_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


security = load_security()

# Assemble provider-shaped negative fixtures at runtime.  Keeping the complete
# token bytes out of Git history lets GitHub push protection distinguish these
# synthetic detector tests from accidentally committed live credentials.
_SLACK_TOKEN_FIXTURE = "xox" + "b-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
_STRIPE_KEY_FIXTURE = "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
_SENDGRID_KEY_FIXTURE = (
    "S" + "G.abcdefghijklmnopqrstuv."
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopq"
)
_GITHUB_PAT_FIXTURE = "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
_GITLAB_PAT_FIXTURE = "gl" + "pat-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
_AWS_ACCESS_KEY_FIXTURE = "AK" + "IAIOSFODNN7EXAMPLE"
_GOOGLE_API_KEY_FIXTURE = "AI" + "zaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
_NPM_TOKEN_FIXTURE = "np" + "m_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
_JWT_FIXTURE = (
    "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
_PYPI_TOKEN_FIXTURE = (
    "py" + "pi-AgEIcHlwaS5vcmcCJDUxMjM0NTY3ODkwYWJjZGVmZ2hpamtsbW5vcA"
)
_PRIVATE_KEY_FIXTURE = (
    "-----BEGIN " + "PRIVATE KEY-----\nraw-private-key-material\n"
    "-----END " + "PRIVATE KEY-----\n"
)
_PGP_PRIVATE_KEY_FIXTURE = (
    "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----\n"
    "Version: test-only\n\npgp-private-key-material\n"
    "-----END " + "PGP PRIVATE KEY BLOCK-----\n"
)
_BASIC_AUTH_FIXTURE = "dX" + "NlcjpiYXNpYy1zZWNyZXQ="


def _fixture_text(*parts: str) -> str:
    return "".join(parts)


def _multiline_secret_cases(secret: str) -> dict[str, str]:
    return {
        "yaml_literal": (
            "password: |-\n"
            f"  {secret}\n"
            "safe: visible\n"
        ),
        "yaml_folded_nested": _fixture_text(
            "services:\n",
            '  - "pass',
            'word": >2-\n',
            f"      {secret}\n",
            "    safe: visible\n",
        ),
        "toml_multiline_basic": (
            'password = """\n'
            f"{secret}\n"
            '"""\n'
            'safe = "visible"\n'
        ),
        "toml_multiline_literal": (
            "password = '''\n"
            f"{secret}\n"
            "'''\n"
            "safe = 'visible'\n"
        ),
    }


class SharedSecretRedactionTests(unittest.TestCase):
    CASES = {
        "authorization_bearer": (
            "Authorization: Bearer dummy-fixture-bearer-token\n",
            ["dummy-fixture-bearer-token"],
        ),
        "authorization_basic": (
            f"Authorization: Basic {_BASIC_AUTH_FIXTURE}\n",
            [_BASIC_AUTH_FIXTURE],
        ),
        "github_pat": (
            _fixture_text("to", "ken=", _GITHUB_PAT_FIXTURE, "\n"),
            [_GITHUB_PAT_FIXTURE],
        ),
        "gitlab_pat": (
            f"{_GITLAB_PAT_FIXTURE}\n",
            [_GITLAB_PAT_FIXTURE],
        ),
        "slack_token_case": (
            f"{_SLACK_TOKEN_FIXTURE}\n",
            [_SLACK_TOKEN_FIXTURE],
        ),
        "cookie_case": (
            "Cookie: token=dummy-fixture-cookie; access_token=dummy-fixture-csrf\n",
            ["dummy-fixture-cookie", "dummy-fixture-csrf"],
        ),
        "aws_credentials": (
            f"AWS_ACCESS_KEY_ID={_AWS_ACCESS_KEY_FIXTURE}\n"
            "AWS_SECRET_ACCESS_KEY=dummy-fixture-aws-secret\n",
            [_AWS_ACCESS_KEY_FIXTURE, "dummy-fixture-aws-secret"],
        ),
        "google_api_key_case": (
            f"{_GOOGLE_API_KEY_FIXTURE}\n",
            [_GOOGLE_API_KEY_FIXTURE],
        ),
        "stripe_live_key": (
            f"{_STRIPE_KEY_FIXTURE}\n",
            [_STRIPE_KEY_FIXTURE],
        ),
        "npm_auth_token_case": (
            _fixture_text(
                "//registry.npmjs.org/:_auth", "Token=", _NPM_TOKEN_FIXTURE, "\n"
            ),
            [_NPM_TOKEN_FIXTURE],
        ),
        "jwt": (
            f"{_JWT_FIXTURE}\n",
            [_JWT_FIXTURE],
        ),
        "private_key_case": (
            _PRIVATE_KEY_FIXTURE,
            ["raw-private-key-material"],
        ),
        "sensitive_url": (
            "https://user:dummy-fixture-url-password@example.test/path?token=dummy-fixture-url-token&safe=visible\n",
            ["dummy-fixture-url-password", "dummy-fixture-url-token"],
        ),
        "azure_sas_url": (
            _fixture_text(
                "https://storage.example.test/container?sv=2024-11-04&s",
                "ig=dummy-fixture-signature\n",
            ),
            ["dummy-fixture-signature"],
        ),
        "generic_oauth_secrets": (
            "client_secret=dummy-fixture-client\naccess_token=dummy-fixture-access\n",
            ["dummy-fixture-client", "dummy-fixture-access"],
        ),
        "yaml_and_toml_scalars": (
            "password: \"dummy-fixture-yaml-password\"\n"
            "service-client-secret: 'dummy-fixture-yaml-client'\n"
            "database_password = \"dummy-fixture-toml-password\"\n"
            "service.api_key = 'dummy-fixture-toml-api'\n"
            "'apiKey': dummy-fixture-yaml-camel\n"
            '"clientSecret" = "dummy-fixture-toml-camel"\n',
            [
                "dummy-fixture-yaml-password",
                "dummy-fixture-yaml-client",
                "dummy-fixture-toml-password",
                "dummy-fixture-toml-api",
                "dummy-fixture-yaml-camel",
                "dummy-fixture-toml-camel",
            ],
        ),
        "cloud_config_credentials": (
            "[default]\n"
            f"aws_access_key_id = {_AWS_ACCESS_KEY_FIXTURE}\n"
            "aws_secret_access_key = dummy-fixture-aws-cloud\n"
            "aws_session_token: dummy-fixture-aws-session\n",
            [
                _AWS_ACCESS_KEY_FIXTURE,
                "dummy-fixture-aws-cloud",
                "dummy-fixture-aws-session",
            ],
        ),
        "netrc_credentials": (
            "machine api.example.test login buildbot password netrc-inline-secret\n"
            "machine second.example.test\n"
            "  login releasebot\n"
            "  password netrc-block-secret\n",
            ["netrc-inline-secret", "netrc-block-secret"],
        ),
        "database_uris": (
            _fixture_text(
                "postgresql+psycopg://alice:",
                "dummy-fixture-postgres@db.example.test/app\n",
                "mysql://bob:",
                "dummy-fixture-mysql@db.example.test/app\n",
                "mongodb+srv://carol:",
                "dummy-fixture-mongo@cluster.example.test/app\n",
                "redis://:",
                "dummy-fixture-redis@cache.example.test/0\n",
            ),
            [
                "dummy-fixture-postgres",
                "dummy-fixture-mysql",
                "dummy-fixture-mongo",
                "dummy-fixture-redis",
            ],
        ),
        "database_connection_string": (
            "Server=db.example.test;User Id=release;Password=dummy-fixture-connection;Encrypt=true\n",
            ["dummy-fixture-connection"],
        ),
        "cli_long_option_credentials": (
            _fixture_text(
                "tool --api", "-key dummy-fixture-cli-plain\n",
                "tool --api", "-key=dummy-fixture-cli-equals\n",
                "tool --access", "-token dummy-fixture-cli-access\n",
                "tool --client", "-secret='dummy-fixture-cli-client'\n",
                "tool --pass", "word \"dummy-fixture-cli-password\"\n",
                "tool --to", "ken dummy-fixture-cli-token\n",
            ),
            [
                "dummy-fixture-cli-plain",
                "dummy-fixture-cli-equals",
                "dummy-fixture-cli-access",
                "dummy-fixture-cli-client",
                "dummy-fixture-cli-password",
                "dummy-fixture-cli-token",
            ],
        ),
        "curl_user_credentials": (
            _fixture_text(
                "curl --us", "er alice:dummy-fixture-curl-long https://example.test\n",
                "curl --us", "er=bob:dummy-fixture-curl-equals https://example.test\n",
                "curl -", "u carol:dummy-fixture-curl-short https://example.test\n",
                "curl -", "udave:dummy-fixture-curl-attached https://example.test\n",
                "curl --proxy", "-user eve:dummy-fixture-curl-proxy https://example.test\n",
            ),
            [
                "dummy-fixture-curl-long",
                "dummy-fixture-curl-equals",
                "dummy-fixture-curl-short",
                "dummy-fixture-curl-attached",
                "dummy-fixture-curl-proxy",
            ],
        ),
        "kubernetes_client_key_data": (
            "client-key-data: ZHVtbXkta3ViZS1jbGllbnQta2V5Cg==\n",
            ["ZHVtbXkta3ViZS1jbGllbnQta2V5Cg=="],
        ),
        "sendgrid_api_key_case": (
            f"{_SENDGRID_KEY_FIXTURE}\n",
            [_SENDGRID_KEY_FIXTURE],
        ),
        "pypi_api_token_case": (
            f"{_PYPI_TOKEN_FIXTURE}\n",
            [_PYPI_TOKEN_FIXTURE],
        ),
        "token_url_username": (
            _fixture_text(
                "https://access-",
                "token-dummy-fixture-1234567890@example.test/private.git\n",
            ),
            ["access-token-dummy-fixture-1234567890"],
        ),
        "pgp_private_key_case": (
            _PGP_PRIVATE_KEY_FIXTURE,
            ["pgp-private-key-material"],
        ),
    }

    def test_json_safe_scalars_are_not_reinterpreted_as_yaml_credentials(self) -> None:
        safe = '{"auth": false, "signature": null, "token": "${TOKEN}"}\n'
        self.assertEqual(security.redact_text(safe), safe)
        unsafe = _fixture_text(
            '{"pass', 'word": "dummy-fixture-synthetic-password"}\n'
        )
        redacted = security.redact_text(unsafe)
        self.assertNotIn("dummy-fixture-synthetic-password", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_multiline_config_secrets_are_fully_redacted_and_idempotent(self) -> None:
        secret = "dummy-fixture-multiline-secret"
        for name, raw in _multiline_secret_cases(secret).items():
            for hmac_key in (None, "multiline-audit-key"):
                with self.subTest(name=name, hmac_key=bool(hmac_key)):
                    redacted = security.redact_text(raw, hmac_key=hmac_key)
                    self.assertNotIn(secret, redacted)
                    self.assertIn("[REDACTED", redacted)
                    self.assertIn("safe", redacted)
                    self.assertIn("visible", redacted)
                    self.assertFalse(security.contains_secret(redacted))
                    self.assertEqual(
                        security.redact_text(redacted, hmac_key=hmac_key),
                        redacted,
                    )

    def test_root_and_escaped_windows_homes_are_redacted(self) -> None:
        root_home = "/" + "root/private-project"
        var_root_home = "/" + "var/root/private-project"
        escaped_windows_home = (
            "C:" + "\\\\" + "Users" + "\\\\Alice\\\\private-project"
        )
        cases = (
            root_home,
            var_root_home,
            json.dumps({"workspace": escaped_windows_home}),
            f'workspace = "{escaped_windows_home}"\n',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                redacted = security.redact_text(raw)
                self.assertNotIn(root_home, redacted)
                self.assertNotIn(var_root_home, redacted)
                self.assertNotIn(escaped_windows_home, redacted)
                self.assertIn("~", redacted)
                self.assertEqual(security.redact_text(redacted), redacted)

    def test_all_common_credentials_are_detected_and_redacted_by_shared_core(self) -> None:
        for name, (raw, secrets) in self.CASES.items():
            with self.subTest(credential=name):
                self.assertTrue(security.contains_secret(raw))
                self.assertTrue(gt.contains_secret(raw))
                shared = security.redact_text(raw)
                core = gt.redact_text(raw)
                self.assertEqual(shared, core)
                self.assertTrue(
                    "[REDACTED" in shared or "%5BREDACTED" in shared,
                    shared,
                )
                for secret in secrets:
                    self.assertNotIn(secret, shared)
                self.assertFalse(security.contains_secret(shared))

    def test_safe_policy_text_is_not_misclassified_as_a_secret(self) -> None:
        safe_cases = (
            "Authorization policy reviewed; token budget is unavailable; Cookie handling documented.",
            "password_policy: strong\ntoken_budget=4096\nclient_secret_name: service-secret\n",
            "page_token=next-page\ncontinuation_token: next-chunk\n",
            "password: ${DB_PASSWORD}\napi_key = {{ secrets.API_KEY }}\nauth: true\n",
            '{"api_key": null, "password_policy": "strict"}\n',
            "postgresql://readonly@db.example.test/app?page_token=next-page\n",
            "private_key_path=/etc/example/key.pem\n",
            "tool --key record-id --page-token next-page --token-budget 4096\n",
            "tool --password-stdin registry.example --token-file /tmp/token-ref\n",
            "tool --api-key $API_KEY --token={{ secrets.ACCESS_TOKEN }}\n",
            "curl --user alice --user alice:${CURL_PASSWORD} https://example.test\n",
            "ssh -p 2222 example.test\n",
            "client-certificate-data: cHVibGljLWNlcnRpZmljYXRl\n",
            "alice@example.test\nhttps://alice@example.test/public.git\n",
            "https://build-service-account@example.test/public.git\n",
            "pypi-package-name\nSG.project.component\n",
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\npublic-material\n"
            "-----END PGP PUBLIC KEY BLOCK-----\n",
        )
        for safe in safe_cases:
            with self.subTest(text=safe):
                self.assertFalse(security.contains_secret(safe))
                self.assertEqual(security.redact_text(safe), safe)

    def test_hmac_marker_is_stable_across_supported_syntax(self) -> None:
        raw = (
            "token=dummy-fixture-same-value\n"
            "Authorization: Bearer dummy-fixture-same-value\n"
            '{"password":"dummy-fixture-same-value"}\n'
        )
        redacted = security.redact_text(raw, hmac_key="audit-key")
        markers = [
            item.split("]", 1)[0] + "]"
            for item in redacted.split("[REDACTED:")[1:]
        ]
        self.assertEqual(len(markers), 3)
        self.assertEqual(len(set(markers)), 1)

    def test_redaction_is_idempotent_with_and_without_hmac(self) -> None:
        raw = _fixture_text(
            "password: dummy-fixture-yaml\n",
            "machine api.example.test login bot password dummy-fixture-netrc\n",
            "mongodb://user:",
            "dummy-fixture-database@cluster.example.test/app\n",
            "Authorization: Bearer dummy-fixture-bearer\n",
            "tool --api", "-key dummy-fixture-cli\n",
            "curl -", "u user:dummy-fixture-curl https://example.test\n",
            "client-key-data: a3ViZS1jbGllbnQta2V5LXNlY3JldA==\n",
            f"{_SENDGRID_KEY_FIXTURE}\n",
        )
        for hmac_key in (None, "stable-audit-key"):
            with self.subTest(hmac_key=bool(hmac_key)):
                once = security.redact_text(raw, hmac_key=hmac_key)
                twice = security.redact_text(once, hmac_key=hmac_key)
                self.assertEqual(twice, once)
                self.assertFalse(security.contains_secret(once))


class PublicArchiveSecurityTests(unittest.TestCase):
    def test_v234_sanitizer_reuses_shared_redaction(self) -> None:
        v234 = require_v234(self)
        raw = (
            "Authorization: Bearer dummy-fixture-archive-token\n"
            "Cookie: token=dummy-fixture-archive-cookie\n"
        )
        sanitized = v234.sanitize_public_text(raw)
        self.assertEqual(sanitized, security.redact_text(raw))
        self.assertNotIn("dummy-fixture-archive-token", sanitized)
        self.assertNotIn("dummy-fixture-archive-cookie", sanitized)
        self.assertFalse(security.contains_secret(sanitized))

    def test_v234_public_copy_never_writes_raw_secret(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            destination = root / "public.md"
            source.write_text(
                "token=dummy-fixture-public-copy\n"
                f"AWS_ACCESS_KEY_ID={_AWS_ACCESS_KEY_FIXTURE}\n",
                encoding="utf-8",
            )
            result = v234.sanitize_public_copy(source, destination)
            self.assertTrue(result["ok"], result)
            public = destination.read_text(encoding="utf-8")
            self.assertNotIn("dummy-fixture-public-copy", public)
            self.assertNotIn(_AWS_ACCESS_KEY_FIXTURE, public)
            self.assertFalse(security.contains_secret(public))

    def test_public_copy_never_leaks_multiline_scalar_bodies(self) -> None:
        v234 = require_v234(self)
        secret = "dummy-fixture-public-multiline"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, raw in _multiline_secret_cases(secret).items():
                with self.subTest(name=name):
                    source = root / f"{name}.source.txt"
                    destination = root / f"{name}.public.txt"
                    source.write_text(raw, encoding="utf-8")
                    result = v234.sanitize_public_copy(source, destination)
                    self.assertTrue(result["ok"], result)
                    public = destination.read_text(encoding="utf-8")
                    self.assertNotIn(secret, public)
                    self.assertIn("visible", public)
                    self.assertFalse(security.contains_secret(public))

    def test_public_copy_sanitizes_all_common_secret_classes(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (raw, secrets) in SharedSecretRedactionTests.CASES.items():
                with self.subTest(credential=name):
                    source = root / f"{name}.source.txt"
                    destination = root / f"{name}.public.txt"
                    source.write_text(raw, encoding="utf-8")
                    result = v234.sanitize_public_copy(source, destination)
                    self.assertTrue(result["ok"], result)
                    public = destination.read_text(encoding="utf-8")
                    for secret in secrets:
                        self.assertNotIn(secret, public)
                    self.assertFalse(security.contains_secret(public))

    def test_public_copy_fails_closed_if_redaction_leaves_a_detectable_secret(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "public.txt"
            source.write_text(
                "api_key=dummy-fixture-redaction-failure\n", encoding="utf-8"
            )
            destination.write_text("known-safe-copy\n", encoding="utf-8")
            before = destination.read_bytes()
            with mock.patch.object(v234, "_redact_text", side_effect=lambda text: text):
                result = v234.sanitize_public_copy(source, destination)
            self.assertFalse(result["ok"], result)
            self.assertEqual(
                result["error_code"], "E_V236_PUBLIC_COPY_REDACTION_FAILED"
            )
            self.assertEqual(destination.read_bytes(), before)

    def test_publish_guard_rejects_every_common_secret_class(self) -> None:
        v234 = require_v234(self)
        for name, (raw, _) in SharedSecretRedactionTests.CASES.items():
            with self.subTest(credential=name):
                self.assertTrue(v234._publish_path_denied("docs/public.md", raw.encode("utf-8")))
                sanitized = security.redact_text(raw)
                self.assertFalse(v234._publish_path_denied("docs/public.md", sanitized.encode("utf-8")))

    def test_public_copy_rejects_non_utf8_without_creating_destination(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            destination = root / "public.bin"
            source.write_bytes(b"prefix\xffapi_key=dummy-fixture-uninspected")
            result = v234.sanitize_public_copy(source, destination)
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["error_code"], "E_V236_PUBLIC_COPY_NON_TEXT")
            self.assertFalse(destination.exists())
            self.assertTrue(v234._publish_path_denied("docs/public.bin", source.read_bytes()))

    def test_public_copy_rejects_control_byte_content_and_preserves_existing_file(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            destination = root / "public.dat"
            source.write_bytes(b"visible-prefix\x00token=dummy-fixture-embedded")
            destination.write_text("known-safe-existing-copy\n", encoding="utf-8")
            before = destination.read_bytes()
            result = v234.sanitize_public_copy(source, destination)
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["error_code"], "E_V236_PUBLIC_COPY_NON_TEXT")
            self.assertEqual(destination.read_bytes(), before)
            self.assertTrue(v234._publish_path_denied("docs/public.dat", source.read_bytes()))


if __name__ == "__main__":
    unittest.main()
