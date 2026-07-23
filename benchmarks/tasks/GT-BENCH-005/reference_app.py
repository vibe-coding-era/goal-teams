#!/usr/bin/env python3
"""Deterministic local order service used by GT-BENCH-005."""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
VALID_DEFECTS = {
    "reference",
    "api_auth_bypass",
    "api_idempotency_broken",
    "api_concurrency_race",
    "api_eventual_consistency_stale",
    "e2e_session_lost",
    "e2e_double_click",
    "e2e_refresh_drops_state",
    "e2e_error_no_recovery",
}


class OrderApplication:
    def __init__(self, db_path: Path, defect: str, browser_read_delay_ms: int):
        self.db_path = db_path
        self.defect = defect
        self.browser_read_delay_seconds = browser_read_delay_ms / 1000
        self.lock = threading.Lock()
        self.fail_next = False
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL
                )
                """
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create_order(
        self, idempotency_key: str, sku: str, quantity: int, *, concurrency_probe: bool
    ) -> tuple[int, dict[str, Any], bool]:
        with self.lock:
            if self.fail_next:
                self.fail_next = False
                return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "transient_failure"}, False

            stored_key = idempotency_key
            if self.defect == "api_idempotency_broken":
                stored_key = f"{idempotency_key}:duplicate:{self.count_orders()}"
            elif self.defect == "api_concurrency_race" and concurrency_probe:
                stored_key = f"{idempotency_key}:race:{self.count_orders()}"

            with self.connect() as connection:
                existing = connection.execute(
                    "SELECT id, idempotency_key, sku, quantity FROM orders WHERE idempotency_key = ?",
                    (stored_key,),
                ).fetchone()
                if existing is not None:
                    return HTTPStatus.OK, dict(existing), True
                cursor = connection.execute(
                    "INSERT INTO orders (idempotency_key, sku, quantity) VALUES (?, ?, ?)",
                    (stored_key, sku, quantity),
                )
                row = connection.execute(
                    "SELECT id, idempotency_key, sku, quantity FROM orders WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
                return HTTPStatus.CREATED, dict(row), False

    def list_orders(self) -> list[dict[str, Any]]:
        if self.defect == "api_eventual_consistency_stale":
            return []
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, idempotency_key, sku, quantity FROM orders ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_orders(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0])


def handler_factory(application: OrderApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "GTBench005/1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(
            self,
            status: int,
            payload: dict[str, Any] | list[dict[str, Any]],
            *,
            replay: bool = False,
        ) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            if replay:
                self.send_header("Idempotent-Replay", "true")
            self.end_headers()
            self.wfile.write(encoded)

        def authenticated(self) -> bool:
            if application.defect == "api_auth_bypass":
                return True
            return self.headers.get("Authorization") == "Bearer gt-bench-session"

        def read_json(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ready", "defect": application.defect})
                return
            if path in {"/", "/index.html"}:
                page = (HERE / "static" / "index.html").read_text(encoding="utf-8")
                page = page.replace("__DEFECT_MODE__", application.defect)
                encoded = page.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if path == "/api/orders":
                if not self.authenticated():
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if (
                    application.browser_read_delay_seconds
                    and "Mozilla/" in self.headers.get("User-Agent", "")
                ):
                    time.sleep(application.browser_read_delay_seconds)
                orders = application.list_orders()
                self.send_json(HTTPStatus.OK, {"orders": orders, "count": len(orders)})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/login":
                self.send_json(HTTPStatus.OK, {"token": "gt-bench-session"})
                return
            if path == "/api/test/fail-next":
                if not self.authenticated():
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                application.fail_next = True
                self.send_json(HTTPStatus.OK, {"armed": True})
                return
            if path == "/api/orders":
                if not self.authenticated():
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                key = self.headers.get("Idempotency-Key", "")
                body = self.read_json()
                if not key or not isinstance(body.get("sku"), str):
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
                    return
                quantity = body.get("quantity")
                if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
                    return
                status, order, replay = application.create_order(
                    key,
                    body["sku"],
                    quantity,
                    concurrency_probe=self.headers.get("X-Concurrency-Probe") == "true",
                )
                self.send_json(status, order, replay=replay)
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--defect", choices=sorted(VALID_DEFECTS), default="reference")
    parser.add_argument("--browser-read-delay-ms", type=int, default=0)
    args = parser.parse_args()
    if args.browser_read_delay_ms < 0 or args.browser_read_delay_ms > 5000:
        parser.error("--browser-read-delay-ms must be between 0 and 5000")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    application = OrderApplication(args.db, args.defect, args.browser_read_delay_ms)
    server = ThreadingHTTPServer((args.host, args.port), handler_factory(application))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
