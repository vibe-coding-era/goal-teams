#!/usr/bin/env python3
"""Run the reproducible API + browser behavior benchmark for Goal Teams V2.44."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "benchmarks" / "tasks" / "GT-BENCH-005"
REFERENCE_APP = TASK_DIR / "reference_app.py"
BROWSER_RUNNER = ROOT / "scripts" / "benchmark" / "v244_testing_capability_browser.cjs"
SCORER_PATH = ROOT / "scripts" / "benchmark" / "v244_testing_capability_scorer.py"
EVIDENCE_SCHEMA = "goal-teams-testing-capability-evidence-v2.44"
RAW_SCHEMA = "goal-teams-testing-capability-raw-observation-v2.44"
RUN_SCHEMA = "goal-teams-testing-capability-run-v2.44"
SUMMARY_SCHEMA = "goal-teams-testing-capability-self-check-v2.44"
E2E_CASE_IDS = (
    "E2E-SESSION-001",
    "E2E-DOUBLE-CLICK-001",
    "E2E-REFRESH-001",
    "E2E-RECOVERY-001",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def artifact_binding(
    evidence_root: Path, path: Path, *, media_type: str
) -> dict[str, Any]:
    root = evidence_root.absolute()
    candidate = path.absolute()
    relative = candidate.relative_to(root).as_posix()
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError(f"artifact must be a regular non-symlink file: {relative}")
    current = root
    for component in Path(relative).parts[:-1]:
        current = current / component
        if current.is_symlink() or not current.is_dir():
            raise RuntimeError(f"artifact ancestor must be a real directory: {relative}")
    return {
        "path": relative,
        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "size": candidate.stat().st_size,
        "media_type": media_type,
    }


def bind_case_artifacts(
    cases: list[dict[str, Any]], run_dir: Path, run_id: str
) -> list[dict[str, Any]]:
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    bound: list[dict[str, Any]] = []
    for case in cases:
        item = dict(case)
        observation = dict(item["evidence"])
        screenshot = observation.get("screenshot")
        if isinstance(screenshot, str):
            observation["screenshot"] = artifact_binding(
                run_dir,
                Path(screenshot),
                media_type="image/png",
            )
        browser_trace = observation.get("browser_trace")
        if isinstance(browser_trace, str):
            observation["browser_trace"] = artifact_binding(
                run_dir,
                Path(browser_trace),
                media_type="application/zip",
            )
        raw_path = raw_dir / f"{item['case_id']}.json"
        write_json(
            raw_path,
            {
                "schema_version": RAW_SCHEMA,
                "run_id": run_id,
                "case_id": item["case_id"],
                "observation": observation,
            },
        )
        item["evidence"] = observation
        item["raw_artifact"] = artifact_binding(
            run_dir,
            raw_path,
            media_type="application/json",
        )
        bound.append(item)
    return bound


def load_scorer() -> Any:
    spec = importlib.util.spec_from_file_location("v244_testing_capability_scorer", SCORER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load benchmark scorer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return {
                "status": response.status,
                "headers": {key.lower(): value for key, value in response.headers.items()},
                "body": json.loads(raw or b"{}"),
            }
    except HTTPError as exc:
        raw = exc.read()
        try:
            response_body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            response_body = {"raw": raw.decode("utf-8", errors="replace")}
        return {
            "status": exc.code,
            "headers": {key.lower(): value for key, value in exc.headers.items()},
            "body": response_body,
        }


def auth_headers(**extra: str) -> dict[str, str]:
    return {"Authorization": "Bearer gt-bench-session", **extra}


def list_orders(base_url: str) -> dict[str, Any]:
    return http_json("GET", f"{base_url}/api/orders", headers=auth_headers())


def order_request(
    base_url: str,
    key: str,
    *,
    concurrency_probe: bool = False,
) -> dict[str, Any]:
    headers = auth_headers(**{"Idempotency-Key": key})
    if concurrency_probe:
        headers["X-Concurrency-Probe"] = "true"
    return http_json(
        "POST",
        f"{base_url}/api/orders",
        payload={"sku": "API-SKU", "quantity": 1},
        headers=headers,
    )


def api_cases(base_url: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    before_auth = list_orders(base_url)["body"]["count"]
    unauthenticated = http_json(
        "POST",
        f"{base_url}/api/orders",
        payload={"sku": "AUTH-SKU", "quantity": 1},
        headers={"Idempotency-Key": "auth-probe"},
    )
    after_auth = list_orders(base_url)["body"]["count"]
    auth_pass = unauthenticated["status"] == 401 and after_auth == before_auth
    cases.append(
        {
            "case_id": "API-AUTH-001",
            "layer": "api",
            "status": "passed" if auth_pass else "failed",
            "behavior_observed": True,
            "evidence": {
                "unauthenticated_status": unauthenticated["status"],
                "count_before": before_auth,
                "count_after": after_auth,
            },
        }
    )

    before_idempotency = list_orders(base_url)["body"]["count"]
    first = order_request(base_url, "sequential-key")
    second = order_request(base_url, "sequential-key")
    after_idempotency = list_orders(base_url)["body"]["count"]
    idempotency_pass = (
        first["status"] == 201
        and second["status"] == 200
        and first["body"].get("id") == second["body"].get("id")
        and second["headers"].get("idempotent-replay") == "true"
        and after_idempotency - before_idempotency == 1
    )
    cases.append(
        {
            "case_id": "API-IDEMPOTENCY-001",
            "layer": "api",
            "status": "passed" if idempotency_pass else "failed",
            "behavior_observed": True,
            "evidence": {
                "statuses": [first["status"], second["status"]],
                "order_ids": [first["body"].get("id"), second["body"].get("id")],
                "replay_header": second["headers"].get("idempotent-replay"),
                "count_delta": after_idempotency - before_idempotency,
            },
        }
    )

    before_concurrency = list_orders(base_url)["body"]["count"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _index: order_request(
                    base_url, "concurrent-key", concurrency_probe=True
                ),
                range(4),
            )
        )
    after_concurrency = list_orders(base_url)["body"]["count"]
    response_ids = [item["body"].get("id") for item in responses]
    concurrency_pass = (
        after_concurrency - before_concurrency == 1
        and responses
        and all(item["status"] in {200, 201} for item in responses)
        and len(set(response_ids)) == 1
        and sum(item["status"] == 201 for item in responses) == 1
    )
    cases.append(
        {
            "case_id": "API-CONCURRENCY-001",
            "layer": "api",
            "status": "passed" if concurrency_pass else "failed",
            "behavior_observed": True,
            "evidence": {
                "statuses": [item["status"] for item in responses],
                "order_ids": response_ids,
                "unique_order_ids": len(set(response_ids)),
                "count_delta": after_concurrency - before_concurrency,
            },
        }
    )

    consistency_create = order_request(base_url, "consistency-key")
    observed = False
    polls: list[dict[str, Any]] = []
    target_id = consistency_create["body"].get("id")
    for _attempt in range(5):
        listed = list_orders(base_url)
        ids = [item.get("id") for item in listed["body"].get("orders", [])]
        polls.append({"status": listed["status"], "order_ids": ids})
        if target_id in ids:
            observed = True
            break
        time.sleep(0.05)
    consistency_pass = consistency_create["status"] == 201 and observed
    cases.append(
        {
            "case_id": "API-CONSISTENCY-001",
            "layer": "api",
            "status": "passed" if consistency_pass else "failed",
            "behavior_observed": True,
            "evidence": {
                "create_status": consistency_create["status"],
                "created_order_id": target_id,
                "polls": polls,
                "observed_within_window": observed,
            },
        }
    )
    return cases


def browser_capability() -> tuple[bool, str | None, str]:
    node = shutil.which("node")
    if node is None:
        return False, None, "node_not_found"
    probe = subprocess.run(
        [node, "-e", "require.resolve('playwright')"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return False, None, "playwright_node_module_not_found"
    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
    )
    chrome = next((str(path) for path in candidates if path.is_file()), None)
    return True, chrome, "available"


def not_run_e2e(reason: str) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "layer": "e2e",
            "status": "not_run",
            "behavior_observed": False,
            "evidence": {"reason": reason},
        }
        for case_id in E2E_CASE_IDS
    ]


def browser_cases(
    base_url: str, evidence_dir: Path, browser_mode: str, run_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if browser_mode == "off":
        return not_run_e2e("browser_execution_explicitly_disabled"), {
            "status": "not_run",
            "reason": "browser_execution_explicitly_disabled",
            "run_id": run_id,
        }
    available, chrome_path, reason = browser_capability()
    if not available:
        return not_run_e2e(reason), {"status": "not_run", "reason": reason, "run_id": run_id}
    command = ["node", str(BROWSER_RUNNER), base_url, str(evidence_dir), run_id]
    if chrome_path:
        command.append(chrome_path)
    process = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=45
    )
    if process.returncode != 0:
        detail = process.stderr[-2000:] or "browser_runner_failed"
        return not_run_e2e(detail), {
            "status": "not_run",
            "reason": "browser_runner_failed",
            "exit_code": process.returncode,
            "stderr": detail,
            "run_id": run_id,
        }
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return not_run_e2e(f"browser_output_invalid_json:{exc}"), {
            "status": "not_run",
            "reason": "browser_output_invalid_json",
            "run_id": run_id,
        }
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return not_run_e2e("browser_cases_missing"), {
            "status": "not_run",
            "reason": "browser_cases_missing",
            "run_id": run_id,
        }
    return cases, {
        "status": "executed",
        "engine": payload.get("runtime", {}).get("engine"),
        "chrome_path": chrome_path,
        "run_id": payload.get("runtime", {}).get("run_id"),
    }


def wait_ready(
    base_url: str,
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"reference app exited early with {process.returncode}")
        try:
            health = http_json("GET", f"{base_url}/health", timeout=0.3)
            if health["status"] == 200:
                return
        except (URLError, TimeoutError):
            pass
        time.sleep(0.05)
    raise RuntimeError("reference app did not become ready")


def canonical_case_outcomes(evidence: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((item["case_id"], item["status"]) for item in evidence["cases"])


def run_candidate(
    mode: str,
    output_dir: Path,
    *,
    browser_mode: str,
    browser_read_delay_ms: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    scorer = load_scorer()
    manifest = scorer.load_canonical_manifest()
    run_dir = output_dir / mode
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    run_id = str(uuid.uuid4())
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    db_path = run_dir / "orders.sqlite3"
    service_log = run_dir / "service.log"
    if db_path.exists():
        db_path.unlink()
    log_handle = service_log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(REFERENCE_APP),
            "--port",
            str(port),
            "--db",
            str(db_path),
            "--defect",
            mode,
            "--browser-read-delay-ms",
            str(browser_read_delay_ms),
            "--run-id",
            run_id,
        ],
        cwd=ROOT,
        text=True,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    cleanup = {"service_terminated": False, "database_retained_for_evidence": True}
    try:
        wait_ready(base_url, process)
        observed_api = api_cases(base_url)
        observed_e2e, browser = browser_cases(
            base_url, run_dir / "screenshots", browser_mode, run_id
        )
        evidence = {
            "schema_version": EVIDENCE_SCHEMA,
            "benchmark_id": manifest["benchmark_id"],
            "candidate": {
                "mode": mode,
                "source": "local_reference_candidate_with_seeded_defect",
            },
            "started_at": started_at,
            "completed_at": utc_now(),
            "cases": [],
            "browser": browser,
            "runtime": {
                "service": "python_threading_http_server",
                "storage": "sqlite",
                "network": "loopback_only",
                "service_log": str(service_log),
                "browser_read_delay_ms": browser_read_delay_ms,
            },
            "cleanup": cleanup,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        cleanup["service_terminated"] = process.poll() is not None
        log_handle.close()

    evidence["cases"] = bind_case_artifacts(
        observed_api + observed_e2e, run_dir, run_id
    )
    evidence["run"] = {
        "schema_version": RUN_SCHEMA,
        "run_id": run_id,
        "candidate_mode": mode,
        "manifest_sha256": scorer.CANONICAL_MANIFEST_SHA256,
        "source_digests": scorer.expected_source_digests(),
        "database_artifact": artifact_binding(
            run_dir, db_path, media_type="application/vnd.sqlite3"
        ),
        "service_log_artifact": artifact_binding(
            run_dir, service_log, media_type="text/plain"
        ),
    }
    score = scorer.score_evidence(evidence, evidence_root=run_dir)
    write_json(run_dir / "evidence.json", evidence)
    write_json(run_dir / "score.json", score)
    return evidence, score


def self_check(output_dir: Path) -> dict[str, Any]:
    scorer = load_scorer()
    manifest = scorer.load_canonical_manifest()
    rows: list[dict[str, Any]] = []
    modes = manifest["candidate_modes"]
    reference_outcomes: list[list[tuple[str, str]]] = []
    failures: list[str] = []
    for candidate in modes:
        mode = candidate["mode"]
        evidence, score = run_candidate(
            mode, output_dir, browser_mode="required"
        )
        outcomes = dict(canonical_case_outcomes(evidence))
        expected = candidate["expected_detected_by"]
        detected = sorted(case_id for case_id in expected if outcomes.get(case_id) == "failed")
        if detected != sorted(expected):
            failures.append(f"{mode}: expected defects not detected: {expected!r}")
        if score["not_run_count"] != 0:
            failures.append(f"{mode}: full self-check contains not_run cases")
        if not evidence["cleanup"]["service_terminated"]:
            failures.append(f"{mode}: service cleanup was not confirmed")
        if mode == "reference":
            if score["score"] != 10.0 or score["not_run_count"] != 0:
                failures.append("reference: expected complete 10/10 behavior score")
            reference_outcomes.append(canonical_case_outcomes(evidence))
        rows.append(
            {
                "mode": mode,
                "score": score["score"],
                "maximum_score": score["maximum_score"],
                "not_run_count": score["not_run_count"],
                "service_terminated": evidence["cleanup"]["service_terminated"],
                "expected_detected_by": expected,
                "detected": detected,
                "evidence_ref": f"{mode}/evidence.json",
                "score_ref": f"{mode}/score.json",
            }
        )

    repeat_evidence, repeat_score = run_candidate(
        "reference", output_dir / "repeat", browser_mode="required"
    )
    reference_outcomes.append(canonical_case_outcomes(repeat_evidence))
    if reference_outcomes[0] != reference_outcomes[1] or repeat_score["score"] != 10.0:
        failures.append("reference: repeated behavior outcomes differ")
    if repeat_score["not_run_count"] != 0:
        failures.append("reference repeat: contains not_run cases")
    if not repeat_evidence["cleanup"]["service_terminated"]:
        failures.append("reference repeat: service cleanup was not confirmed")

    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "benchmark_id": manifest["benchmark_id"],
        "status": "passed" if not failures else "failed",
        "behavior_run": "executed",
        "reference_repeatable": reference_outcomes[0] == reference_outcomes[1],
        "not_run_count_total": sum(row["not_run_count"] for row in rows)
        + repeat_score["not_run_count"],
        "all_services_terminated": all(row["service_terminated"] for row in rows)
        and repeat_evidence["cleanup"]["service_terminated"],
        "candidate_runs": rows,
        "failures": failures,
        "oracle_digest": hashlib.sha256(
            json.dumps(
                [(row["mode"], row["expected_detected_by"]) for row in rows],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "non_behavior_inputs_counted": False,
    }
    write_json(output_dir / "self-check-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-mode", default="reference")
    parser.add_argument("--browser", choices=("auto", "required", "off"), default="auto")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    scorer = load_scorer()
    manifest = scorer.load_canonical_manifest()
    valid_modes = {item["mode"] for item in manifest["candidate_modes"]}
    if args.candidate_mode not in valid_modes:
        print(f"unknown candidate mode: {args.candidate_mode}", file=sys.stderr)
        return 2

    if args.self_check:
        result = self_check(args.output_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "passed" else 1

    evidence, score = run_candidate(
        args.candidate_mode,
        args.output_dir,
        browser_mode=args.browser,
    )
    if args.browser == "required" and evidence["browser"]["status"] != "executed":
        print(json.dumps(score, ensure_ascii=False, sort_keys=True))
        return 3
    print(json.dumps(score, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
