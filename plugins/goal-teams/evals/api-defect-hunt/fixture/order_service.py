#!/usr/bin/env python3
"""Order service: a small loopback HTTP API backed by SQLite (stdlib only).

Run it:    python3 order_service.py --port 8765 --db data/orders.db
In tests:  base_url, stop = start_server("data/test.db")  # port picked automatically
The API contract lives in API.md.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
SESSION_TOKEN = "demo-session-token"
DEMO_ORDERS = (
    ("demo-order-1", "DEMO-SKU-1", 1),
    ("demo-order-2", "DEMO-SKU-2", 2),
)
# Creating an order first reserves stock in the (simulated) warehouse service.
WAREHOUSE_LATENCY_SECONDS = 0.2


class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    """Bind a numeric loopback address without reverse-DNS lookup."""

    daemon_threads = True

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class OrderApplication:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fail_next = threading.Event()
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL
                )
                """
            )
            (existing,) = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
            if existing == 0:
                conn.executemany(
                    "INSERT INTO orders (idempotency_key, sku, quantity) VALUES (?, ?, ?)",
                    DEMO_ORDERS,
                )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def find_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, idempotency_key, sku, quantity FROM orders WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def reserve_stock(self, sku: str, quantity: int) -> None:
        time.sleep(WAREHOUSE_LATENCY_SECONDS)

    def create_order(self, key: str, sku: str, quantity: int) -> Tuple[int, Dict[str, Any], bool]:
        existing = self.find_by_key(key)
        if existing is not None:
            return HTTPStatus.OK, existing, True
        if self.fail_next.is_set():
            self.fail_next.clear()
            return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "transient_failure"}, False
        self.reserve_stock(sku, quantity)
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO orders (idempotency_key, sku, quantity) VALUES (?, ?, ?)",
                (key, sku, quantity),
            )
            row = conn.execute(
                "SELECT id, idempotency_key, sku, quantity FROM orders WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return HTTPStatus.CREATED, dict(row), False

    def list_orders(self) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            # The newest row may still be in flight, so the read side stops just before it.
            (newest,) = conn.execute("SELECT COALESCE(MAX(id), 0) FROM orders").fetchone()
            rows = conn.execute(
                "SELECT id, idempotency_key, sku, quantity FROM orders WHERE id < ? ORDER BY id",
                (newest,),
            ).fetchall()
        return [dict(row) for row in rows]


def handler_factory(app: OrderApplication) -> Type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OrderService/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def send_json(self, status: int, payload: Any, *, replay: bool = False) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if replay:
                self.send_header("Idempotent-Replay", "true")
            self.end_headers()
            self.wfile.write(body)

        def authenticated(self) -> bool:
            header = self.headers.get("Authorization")
            if header is None:
                # Local admin tooling (cron jobs, scripts) calls without a token.
                return self.client_address[0] == HOST
            return header == f"Bearer {SESSION_TOKEN}"

        def read_json(self) -> Dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}
            return value if isinstance(value, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ready"})
            elif path in ("/", "/index.html"):
                page = (HERE / "static" / "index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif path == "/api/orders":
                if not self.authenticated():
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                orders = app.list_orders()
                self.send_json(HTTPStatus.OK, {"orders": orders, "count": len(orders)})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/login":
                self.send_json(HTTPStatus.OK, {"token": SESSION_TOKEN})
                return
            if path not in ("/api/orders", "/api/test/fail-next"):
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self.authenticated():
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            if path == "/api/test/fail-next":
                app.fail_next.set()
                self.send_json(HTTPStatus.OK, {"armed": True})
                return
            key = self.headers.get("Idempotency-Key", "")
            body = self.read_json()
            sku = body.get("sku")
            quantity = body.get("quantity")
            if (
                not key
                or not isinstance(sku, str)
                or not sku
                or not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
            ):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
                return
            status, order, replay = app.create_order(key, sku, quantity)
            self.send_json(status, order, replay=replay)

    return Handler


def start_server(db_path: str, port: int = 0) -> Tuple[str, Callable[[], None]]:
    """Start the service in a background thread and return (base_url, stop)."""
    app = OrderApplication(Path(db_path))
    server = LoopbackThreadingHTTPServer((HOST, port), handler_factory(app))
    thread = threading.Thread(target=server.serve_forever, name="order-service", daemon=True)
    thread.start()

    def stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return f"http://{HOST}:{server.server_port}", stop


def main() -> int:
    parser = argparse.ArgumentParser(description="Order service (listens on 127.0.0.1 only)")
    parser.add_argument("--port", type=int, default=8765, help="0 picks a free port")
    parser.add_argument("--db", type=Path, default=HERE / "data" / "orders.db")
    args = parser.parse_args()
    app = OrderApplication(args.db)
    server = LoopbackThreadingHTTPServer((HOST, args.port), handler_factory(app))
    print(json.dumps({"event": "ready", "url": f"http://{HOST}:{server.server_port}"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
