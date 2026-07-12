"""V2.36 shared secret redaction and public archive negative tests."""

from __future__ import annotations

import importlib.util
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


class SharedSecretRedactionTests(unittest.TestCase):
    CASES = {
        "authorization_bearer": (
            "Authorization: Bearer bearer-secret-token-123456\n",
            ["bearer-secret-token-123456"],
        ),
        "authorization_basic": (
            "Authorization: Basic dXNlcjpiYXNpYy1zZWNyZXQ=\n",
            ["dXNlcjpiYXNpYy1zZWNyZXQ="],
        ),
        "github_pat": (
            "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n",
            ["ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"],
        ),
        "gitlab_pat": (
            "glpat-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n",
            ["glpat-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"],
        ),
        "slack_token": (
            f"{_SLACK_TOKEN_FIXTURE}\n",
            [_SLACK_TOKEN_FIXTURE],
        ),
        "cookie": (
            "Cookie: session=super-secret-session; csrf=super-secret-csrf\n",
            ["super-secret-session", "super-secret-csrf"],
        ),
        "aws_credentials": (
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
            ["AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"],
        ),
        "google_api_key": (
            "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n",
            ["AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"],
        ),
        "stripe_live_key": (
            f"{_STRIPE_KEY_FIXTURE}\n",
            [_STRIPE_KEY_FIXTURE],
        ),
        "npm_auth_token": (
            "//registry.npmjs.org/:_authToken=npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n",
            ["npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"],
        ),
        "jwt": (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n",
            [
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
            ],
        ),
        "private_key": (
            "-----BEGIN PRIVATE KEY-----\nraw-private-key-material\n"
            "-----END PRIVATE KEY-----\n",
            ["raw-private-key-material"],
        ),
        "sensitive_url": (
            "https://user:password-value@example.test/path?token=url-secret-token&safe=visible\n",
            ["password-value", "url-secret-token"],
        ),
        "azure_sas_url": (
            "https://storage.example.test/container?sv=2024-11-04&sig=azure-signature-secret\n",
            ["azure-signature-secret"],
        ),
        "generic_oauth_secrets": (
            "client_secret=generic-client-secret\naccess_token=generic-access-token\n",
            ["generic-client-secret", "generic-access-token"],
        ),
        "yaml_and_toml_scalars": (
            "password: \"yaml-password-secret\"\n"
            "service-client-secret: 'yaml-client-secret'\n"
            "database_password = \"toml-password-secret\"\n"
            "service.api_key = 'toml-api-key-secret'\n"
            "'apiKey': yaml-camel-api-secret\n"
            '"clientSecret" = "toml-camel-client-secret"\n',
            [
                "yaml-password-secret",
                "yaml-client-secret",
                "toml-password-secret",
                "toml-api-key-secret",
                "yaml-camel-api-secret",
                "toml-camel-client-secret",
            ],
        ),
        "cloud_config_credentials": (
            "[default]\n"
            "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"
            "aws_secret_access_key = aws-cloud-secret-value\n"
            "aws_session_token: aws-session-secret-value\n",
            [
                "AKIAIOSFODNN7EXAMPLE",
                "aws-cloud-secret-value",
                "aws-session-secret-value",
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
            "postgresql+psycopg://alice:postgres-secret@db.example.test/app\n"
            "mysql://bob:mysql-secret@db.example.test/app\n"
            "mongodb+srv://carol:mongo-secret@cluster.example.test/app\n"
            "redis://:redis-secret@cache.example.test/0\n",
            ["postgres-secret", "mysql-secret", "mongo-secret", "redis-secret"],
        ),
        "database_connection_string": (
            "Server=db.example.test;User Id=release;Password=connection-secret;Encrypt=true\n",
            ["connection-secret"],
        ),
        "cli_long_option_credentials": (
            "tool --api-key plain-cli-api-secret\n"
            "tool --api-key=equals-cli-api-secret\n"
            "tool --access-token access-cli-secret\n"
            "tool --client-secret='client-cli-secret'\n"
            "tool --password \"password-cli-secret\"\n"
            "tool --token token-cli-secret\n",
            [
                "plain-cli-api-secret",
                "equals-cli-api-secret",
                "access-cli-secret",
                "client-cli-secret",
                "password-cli-secret",
                "token-cli-secret",
            ],
        ),
        "curl_user_credentials": (
            "curl --user alice:curl-long-secret https://example.test\n"
            "curl --user=bob:curl-equals-secret https://example.test\n"
            "curl -u carol:curl-short-secret https://example.test\n"
            "curl -udave:curl-attached-secret https://example.test\n"
            "curl --proxy-user eve:curl-proxy-secret https://example.test\n",
            [
                "curl-long-secret",
                "curl-equals-secret",
                "curl-short-secret",
                "curl-attached-secret",
                "curl-proxy-secret",
            ],
        ),
        "kubernetes_client_key_data": (
            "client-key-data: ZHVtbXkta3ViZS1jbGllbnQta2V5Cg==\n",
            ["ZHVtbXkta3ViZS1jbGllbnQta2V5Cg=="],
        ),
        "sendgrid_api_key": (
            f"{_SENDGRID_KEY_FIXTURE}\n",
            [_SENDGRID_KEY_FIXTURE],
        ),
        "pypi_api_token": (
            "pypi-AgEIcHlwaS5vcmcCJDUxMjM0NTY3ODkwYWJjZGVmZ2hpamtsbW5vcA\n",
            [
                "pypi-AgEIcHlwaS5vcmcCJDUxMjM0NTY3ODkwYWJjZGVmZ2hpamtsbW5vcA"
            ],
        ),
        "token_url_username": (
            "https://access-token-url-secret-1234567890@example.test/private.git\n",
            ["access-token-url-secret-1234567890"],
        ),
        "pgp_private_key": (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "Version: test-only\n\n"
            "pgp-private-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----\n",
            ["pgp-private-key-material"],
        ),
    }

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
            "token=same-secret-value\n"
            "Authorization: Bearer same-secret-value\n"
            '{"password":"same-secret-value"}\n'
        )
        redacted = security.redact_text(raw, hmac_key="audit-key")
        markers = [
            item.split("]", 1)[0] + "]"
            for item in redacted.split("[REDACTED:")[1:]
        ]
        self.assertEqual(len(markers), 3)
        self.assertEqual(len(set(markers)), 1)

    def test_redaction_is_idempotent_with_and_without_hmac(self) -> None:
        raw = (
            "password: yaml-secret\n"
            "machine api.example.test login bot password netrc-secret\n"
            "mongodb://user:database-secret@cluster.example.test/app\n"
            "Authorization: Bearer bearer-secret-value\n"
            "tool --api-key cli-secret-value\n"
            "curl -u user:curl-secret-value https://example.test\n"
            "client-key-data: a3ViZS1jbGllbnQta2V5LXNlY3JldA==\n"
            f"{_SENDGRID_KEY_FIXTURE}\n"
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
        raw = "Authorization: Bearer archive-secret-token\nCookie: sid=archive-cookie-secret\n"
        sanitized = v234.sanitize_public_text(raw)
        self.assertEqual(sanitized, security.redact_text(raw))
        self.assertNotIn("archive-secret-token", sanitized)
        self.assertNotIn("archive-cookie-secret", sanitized)
        self.assertFalse(security.contains_secret(sanitized))

    def test_v234_public_copy_never_writes_raw_secret(self) -> None:
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            destination = root / "public.md"
            source.write_text(
                "token=public-copy-secret\n"
                "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n",
                encoding="utf-8",
            )
            result = v234.sanitize_public_copy(source, destination)
            self.assertTrue(result["ok"], result)
            public = destination.read_text(encoding="utf-8")
            self.assertNotIn("public-copy-secret", public)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", public)
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
            source.write_text("api_key=redaction-failure-secret\n", encoding="utf-8")
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
            source.write_bytes(b"prefix\xffapi_key=uninspected-secret")
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
            source.write_bytes(b"visible-prefix\x00token=embedded-secret")
            destination.write_text("known-safe-existing-copy\n", encoding="utf-8")
            before = destination.read_bytes()
            result = v234.sanitize_public_copy(source, destination)
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["error_code"], "E_V236_PUBLIC_COPY_NON_TEXT")
            self.assertEqual(destination.read_bytes(), before)
            self.assertTrue(v234._publish_path_denied("docs/public.dat", source.read_bytes()))


if __name__ == "__main__":
    unittest.main()
