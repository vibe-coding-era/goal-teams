#!/usr/bin/env python3
"""Compare screenshots with tolerance, masks, MAE, critical regions, and provenance."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable


Pixel = tuple[int, int, int]
ENVIRONMENT_KEYS = ("browser", "browser_version", "viewport", "dpr", "fonts", "os")
UI_MODES = {"original", "replica"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ppm(path: Path) -> tuple[int, int, list[Pixel]]:
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError(f"{path} is not a binary PPM (P6). Install Pillow for PNG/JPEG support.")
    tokens: list[bytes] = []
    idx = 2
    while len(tokens) < 3:
        while idx < len(data) and data[idx:idx + 1].isspace():
            idx += 1
        if data[idx:idx + 1] == b"#":
            while data[idx:idx + 1] not in {b"\n", b""}:
                idx += 1
            continue
        start = idx
        while idx < len(data) and not data[idx:idx + 1].isspace():
            idx += 1
        tokens.append(data[start:idx])
    width, height, max_value = map(int, tokens)
    if width <= 0 or height <= 0 or max_value != 255:
        raise ValueError("PPM width/height must be positive and max_value must be 255")
    if idx >= len(data) or not data[idx:idx + 1].isspace():
        raise ValueError(f"{path} is missing the PPM header separator")
    if data[idx:idx + 2] == b"\r\n":
        idx += 2
    else:
        idx += 1
    raw = data[idx:]
    if len(raw) != width * height * 3:
        raise ValueError(f"{path} pixel count mismatch")
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    return width, height, pixels


def read_image(path: Path) -> tuple[int, int, list[Pixel]]:
    if path.suffix.lower() == ".ppm":
        return read_ppm(path)
    try:
        from PIL import Image  # type: ignore
    except ModuleNotFoundError as exc:
        raise ValueError(f"{path} requires Pillow for non-PPM image decoding") from exc
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        return width, height, list(rgb.getdata())


def write_ppm(path: Path, width: int, height: int, pixels: Iterable[Pixel]) -> None:
    body = bytearray()
    for red, green, blue in pixels:
        body.extend((red, green, blue))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(body))


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def validate_threshold(value: float, label: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{label} must be between 0 and 1")


def load_regions(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid critical regions JSON: {path}") from exc
    if not isinstance(payload, list):
        raise ValueError("critical regions JSON must be a list")
    regions: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, region in enumerate(payload):
        if not isinstance(region, dict):
            raise ValueError(f"critical region {index} must be an object")
        name = region.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"critical region {index} has an invalid or duplicate name")
        names.add(name)
        coordinates = [region.get(key) for key in ("x", "y", "width", "height")]
        if not all(isinstance(value, int) for value in coordinates):
            raise ValueError(f"critical region {name} coordinates must be integers")
        if coordinates[0] < 0 or coordinates[1] < 0 or coordinates[2] <= 0 or coordinates[3] <= 0:
            raise ValueError(f"critical region {name} has invalid geometry")
        changed_limit = float(region.get("changed_ratio_threshold", 0.0))
        mae_limit = float(region.get("mae_threshold", 0.0))
        validate_threshold(changed_limit, f"critical region {name} changed ratio threshold")
        validate_threshold(mae_limit, f"critical region {name} MAE threshold")
        regions.append({
            "name": name,
            "x": coordinates[0],
            "y": coordinates[1],
            "width": coordinates[2],
            "height": coordinates[3],
            "changed_ratio_threshold": changed_limit,
            "mae_threshold": mae_limit,
        })
    return regions


def validate_environment(payload: dict[str, Any], label: str) -> dict[str, Any]:
    missing = [
        key for key in ENVIRONMENT_KEYS
        if key not in payload or payload[key] is None or payload[key] == ""
    ]
    if missing:
        raise ValueError(f"{label} environment missing: {','.join(missing)}")
    for key in ("browser", "browser_version", "viewport", "os"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ValueError(f"{label} environment {key} must be a non-empty string")
    dpr = payload["dpr"]
    if isinstance(dpr, bool) or not isinstance(dpr, (int, float)) or dpr <= 0:
        raise ValueError(f"{label} environment dpr must be a positive number")
    if not isinstance(payload["fonts"], list) or not payload["fonts"]:
        raise ValueError(f"{label} environment fonts must be a non-empty list")
    if not all(isinstance(font, str) and font.strip() for font in payload["fonts"]):
        raise ValueError(f"{label} environment font entries must be non-empty strings")
    return {key: payload[key] for key in ENVIRONMENT_KEYS}


def environment_result(
    baseline_path: Path | None,
    actual_path: Path | None,
    require_environment: bool,
) -> dict[str, Any]:
    if baseline_path is None and actual_path is None:
        return {"provided": False, "required": require_environment, "comparable": not require_environment}
    if baseline_path is None or actual_path is None:
        raise ValueError("baseline and actual environment metadata must be provided together")
    baseline = validate_environment(load_json_object(baseline_path, "baseline environment"), "baseline")
    actual = validate_environment(load_json_object(actual_path, "actual environment"), "actual")
    mismatches = [key for key in ENVIRONMENT_KEYS if baseline[key] != actual[key]]
    return {
        "provided": True,
        "required": require_environment,
        "comparable": not mismatches,
        "mismatched_fields": mismatches,
        "baseline": baseline,
        "actual": actual,
    }


def approval_result(path: Path | None, baseline_sha256: str, required: bool) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "required": required, "valid": not required}
    payload = load_json_object(path, "baseline approval")
    required_fields = ("reviewer_run_id", "approved_at", "reason", "baseline_sha256")
    missing = [key for key in required_fields if not isinstance(payload.get(key), str) or not payload[key].strip()]
    timestamp_valid = False
    if "approved_at" not in missing:
        try:
            approved_at = payload["approved_at"].replace("Z", "+00:00")
            timestamp_valid = dt.datetime.fromisoformat(approved_at).tzinfo is not None
        except ValueError:
            timestamp_valid = False
    valid = not missing and timestamp_valid and payload.get("baseline_sha256") == baseline_sha256
    return {
        "provided": True,
        "required": required,
        "valid": valid,
        "missing_fields": missing,
        "hash_matches": payload.get("baseline_sha256") == baseline_sha256,
        "timestamp_valid": timestamp_valid,
        "reviewer_run_id": payload.get("reviewer_run_id"),
        "approved_at": payload.get("approved_at"),
        "reason": payload.get("reason"),
        "change_reason": payload.get("reason"),
    }


def metric_for_indices(
    indices: Iterable[int],
    raw_deltas: list[tuple[int, int, int]],
    effective_deltas: list[tuple[int, int, int]],
    ignored: list[bool],
) -> dict[str, Any]:
    evaluated = 0
    changed = 0
    raw_total = 0
    effective_total = 0
    max_delta = 0
    for index in indices:
        if ignored[index]:
            continue
        evaluated += 1
        raw = raw_deltas[index]
        effective = effective_deltas[index]
        raw_total += sum(raw)
        effective_total += sum(effective)
        max_delta = max(max_delta, sum(effective))
        if any(effective):
            changed += 1
    changed_ratio = changed / evaluated if evaluated else 0.0
    mae = effective_total / (evaluated * 3 * 255) if evaluated else 0.0
    raw_mae = raw_total / (evaluated * 3 * 255) if evaluated else 0.0
    return {
        "evaluated_pixels": evaluated,
        "changed_pixels": changed,
        "changed_ratio": changed_ratio,
        "mae": mae,
        "raw_mae": raw_mae,
        "max_effective_delta": max_delta,
    }


def compare(
    a_path: Path,
    b_path: Path,
    changed_ratio_threshold: float,
    mae_threshold: float,
    color_tolerance: int,
    diff_path: Path | None,
    *,
    mask_path: Path | None = None,
    regions_path: Path | None = None,
    baseline_environment_path: Path | None = None,
    actual_environment_path: Path | None = None,
    baseline_approval_path: Path | None = None,
    require_environment: bool = False,
    require_baseline_approval: bool = False,
    ui_mode: str = "original",
) -> dict[str, object]:
    validate_threshold(changed_ratio_threshold, "changed ratio threshold")
    validate_threshold(mae_threshold, "MAE threshold")
    if color_tolerance < 0 or color_tolerance > 255:
        raise ValueError("color tolerance must be between 0 and 255")
    if ui_mode not in UI_MODES:
        raise ValueError(f"ui_mode must be one of: {','.join(sorted(UI_MODES))}")
    reference_driven = ui_mode == "replica"
    effective_require_environment = require_environment or reference_driven
    effective_require_baseline_approval = require_baseline_approval or reference_driven
    if reference_driven:
        try:
            same_input = a_path.samefile(b_path)
        except OSError:
            same_input = a_path.resolve() == b_path.resolve()
        if same_input:
            raise ValueError("replica baseline and actual must be distinct files")
    if diff_path is not None:
        protected_inputs = {a_path.resolve(), b_path.resolve()}
        if mask_path is not None:
            protected_inputs.add(mask_path.resolve())
        if diff_path.resolve() in protected_inputs:
            raise ValueError("diff output must not overwrite a baseline, actual, or mask image")
    width_a, height_a, pixels_a = read_image(a_path)
    width_b, height_b, pixels_b = read_image(b_path)
    if (width_a, height_a) != (width_b, height_b):
        raise ValueError(f"Image dimensions differ: {width_a}x{height_a} vs {width_b}x{height_b}")

    total = width_a * height_a
    ignored = [False] * total
    if mask_path is not None:
        mask_width, mask_height, mask_pixels = read_image(mask_path)
        if (mask_width, mask_height) != (width_a, height_a):
            raise ValueError("mask dimensions differ from screenshots")
        ignored = [any(pixel) for pixel in mask_pixels]

    raw_deltas: list[tuple[int, int, int]] = []
    effective_deltas: list[tuple[int, int, int]] = []
    diff_pixels: list[Pixel] = []
    for index, (left, right) in enumerate(zip(pixels_a, pixels_b)):
        raw = tuple(abs(x - y) for x, y in zip(left, right))
        effective = tuple(max(0, value - color_tolerance) for value in raw)
        raw_deltas.append(raw)  # type: ignore[arg-type]
        effective_deltas.append(effective)  # type: ignore[arg-type]
        if ignored[index]:
            diff_pixels.append((0, 0, 80))
        elif any(effective):
            diff_pixels.append((min(255, sum(effective)), 0, 0))
        else:
            diff_pixels.append((0, 0, 0))

    metrics = metric_for_indices(range(total), raw_deltas, effective_deltas, ignored)
    global_passed = (
        metrics["evaluated_pixels"] > 0
        and metrics["changed_ratio"] <= changed_ratio_threshold
        and metrics["mae"] <= mae_threshold
    )

    critical_regions: list[dict[str, Any]] = []
    for region in load_regions(regions_path):
        if region["x"] + region["width"] > width_a or region["y"] + region["height"] > height_a:
            raise ValueError(f"critical region {region['name']} exceeds image bounds")
        indices = [
            y * width_a + x
            for y in range(region["y"], region["y"] + region["height"])
            for x in range(region["x"], region["x"] + region["width"])
        ]
        region_metrics = metric_for_indices(indices, raw_deltas, effective_deltas, ignored)
        region_passed = (
            region_metrics["evaluated_pixels"] > 0
            and region_metrics["changed_ratio"] <= region["changed_ratio_threshold"]
            and region_metrics["mae"] <= region["mae_threshold"]
        )
        critical_regions.append({**region, **region_metrics, "passed": region_passed})

    baseline_hash = sha256(a_path)
    environment = environment_result(
        baseline_environment_path, actual_environment_path, effective_require_environment
    )
    approval = approval_result(
        baseline_approval_path, baseline_hash, effective_require_baseline_approval
    )
    if diff_path:
        write_ppm(diff_path, width_a, height_a, diff_pixels)
    passed = global_passed and all(region["passed"] for region in critical_regions)
    passed = passed and bool(environment["comparable"]) and bool(approval["valid"])
    return {
        "schema_version": "goal-teams-pixel-diff-v2.3",
        "ui_mode": ui_mode,
        "reference_driven": reference_driven,
        "width": width_a,
        "height": height_a,
        "total_pixels": total,
        "ignored_pixels": sum(ignored),
        **metrics,
        "changed_ratio_threshold": changed_ratio_threshold,
        "mae_threshold": mae_threshold,
        "color_tolerance": color_tolerance,
        "global_passed": global_passed,
        "critical_regions": critical_regions,
        "environment": environment,
        "baseline_approval": approval,
        "requirements": {
            "environment_fingerprint": effective_require_environment,
            "independent_baseline_approval": effective_require_baseline_approval,
            "baseline_change_reason": effective_require_baseline_approval,
        },
        "baseline_sha256": baseline_hash,
        "actual_sha256": sha256(b_path),
        "mask_sha256": sha256(mask_path) if mask_path else None,
        "passed": passed,
        "diff_path": str(diff_path) if diff_path else None,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline.ppm"
        actual = root / "actual.ppm"
        mask = root / "mask.ppm"
        write_ppm(baseline, 3, 1, [(0, 0, 0)] * 3)
        write_ppm(actual, 3, 1, [(2, 2, 2), (255, 0, 0), (255, 0, 0)])
        write_ppm(mask, 3, 1, [(0, 0, 0), (255, 255, 255), (0, 0, 0)])
        regions = root / "regions.json"
        regions.write_text(json.dumps([{
            "name": "critical-button", "x": 2, "y": 0, "width": 1, "height": 1,
            "changed_ratio_threshold": 1.0, "mae_threshold": 0.34,
        }]), encoding="utf-8")
        environment = {
            "browser": "Chromium", "browser_version": "1", "viewport": "3x1",
            "dpr": 1, "fonts": ["Test Sans"], "os": "test",
        }
        baseline_environment = root / "baseline-env.json"
        actual_environment = root / "actual-env.json"
        baseline_environment.write_text(json.dumps(environment), encoding="utf-8")
        actual_environment.write_text(json.dumps(environment), encoding="utf-8")
        approval = root / "approval.json"
        approval.write_text(json.dumps({
            "reviewer_run_id": "review-run-independent",
            "approved_at": "2026-07-10T00:00:00Z",
            "reason": "approved deterministic baseline fixture",
            "baseline_sha256": sha256(baseline),
        }), encoding="utf-8")
        result = compare(
            baseline, actual, 0.5, 0.2, 3, root / "diff.ppm",
            mask_path=mask, regions_path=regions,
            baseline_environment_path=baseline_environment,
            actual_environment_path=actual_environment,
            baseline_approval_path=approval,
            ui_mode="replica",
        )
        if (
            not result["passed"]
            or result["changed_pixels"] != 1
            or result["ignored_pixels"] != 1
            or result["environment"]["required"] is not True
            or result["baseline_approval"]["required"] is not True
        ):
            raise AssertionError(result)
        replica_without_provenance = compare(
            baseline, actual, 0.0, 0.0, 0, None, ui_mode="replica"
        )
        if replica_without_provenance["passed"]:
            raise AssertionError("replica mode accepted missing environment/approval provenance")
        if (
            replica_without_provenance["environment"]["required"] is not True
            or replica_without_provenance["baseline_approval"]["required"] is not True
        ):
            raise AssertionError("replica mode did not activate provenance requirements")
        original_without_reference = compare(
            baseline, baseline, 0.0, 0.0, 0, None, ui_mode="original"
        )
        if not original_without_reference["passed"]:
            raise AssertionError("original UI was incorrectly forced to provide a reference baseline")
        strict_regions = root / "strict-regions.json"
        strict_regions.write_text(json.dumps([{
            "name": "critical-button", "x": 2, "y": 0, "width": 1, "height": 1,
            "changed_ratio_threshold": 0.0, "mae_threshold": 0.0,
        }]), encoding="utf-8")
        failed = compare(
            baseline, actual, 1.0, 1.0, 3, None,
            mask_path=mask, regions_path=strict_regions,
        )
        if failed["passed"]:
            raise AssertionError("critical region regression was not rejected")
        different_environment = dict(environment, browser_version="2")
        actual_environment.write_text(json.dumps(different_environment), encoding="utf-8")
        failed_environment = compare(
            baseline, actual, 1.0, 1.0, 0, None,
            baseline_environment_path=baseline_environment,
            actual_environment_path=actual_environment,
            require_environment=True,
        )
        if failed_environment["passed"]:
            raise AssertionError("incomparable environments were not rejected")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", nargs="?")
    parser.add_argument("actual", nargs="?")
    parser.add_argument("--threshold", type=float, default=0.01, help="maximum changed-pixel ratio")
    parser.add_argument("--mae-threshold", type=float, default=0.01, help="maximum normalized mean absolute error")
    parser.add_argument("--color-tolerance", type=int, default=0, help="per-channel anti-aliasing tolerance (0-255)")
    parser.add_argument("--mask", help="non-black pixels are excluded as dynamic regions")
    parser.add_argument("--critical-regions", help="JSON list of named region thresholds")
    parser.add_argument("--baseline-environment", help="baseline browser/viewport/font/OS metadata JSON")
    parser.add_argument("--actual-environment", help="actual browser/viewport/font/OS metadata JSON")
    parser.add_argument("--baseline-approval", help="independent reviewer baseline approval JSON")
    parser.add_argument(
        "--ui-mode", choices=sorted(UI_MODES), default="original",
        help="replica automatically requires environment fingerprints and baseline approval",
    )
    parser.add_argument("--require-environment", action="store_true")
    parser.add_argument("--require-baseline-approval", action="store_true")
    parser.add_argument("--diff", help="optional output diff PPM path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Pixel diff V2.3 self-test passed.")
        return
    if not args.baseline or not args.actual:
        parser.error("baseline and actual images are required")
    try:
        result = compare(
            Path(args.baseline), Path(args.actual), args.threshold, args.mae_threshold,
            args.color_tolerance, Path(args.diff) if args.diff else None,
            mask_path=Path(args.mask) if args.mask else None,
            regions_path=Path(args.critical_regions) if args.critical_regions else None,
            baseline_environment_path=Path(args.baseline_environment) if args.baseline_environment else None,
            actual_environment_path=Path(args.actual_environment) if args.actual_environment else None,
            baseline_approval_path=Path(args.baseline_approval) if args.baseline_approval else None,
            require_environment=args.require_environment,
            require_baseline_approval=args.require_baseline_approval,
            ui_mode=args.ui_mode,
        )
    except ValueError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
