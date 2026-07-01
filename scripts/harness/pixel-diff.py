#!/usr/bin/env python3
"""Compare two screenshots and emit deterministic pixel-diff metrics."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Iterable


Pixel = tuple[int, int, int]


def read_ppm(path: Path) -> tuple[int, int, list[Pixel]]:
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError(f"{path} is not a binary PPM (P6). Install Pillow for PNG/JPEG support.")
    tokens: list[bytes] = []
    idx = 2
    while len(tokens) < 3:
        while data[idx:idx + 1].isspace():
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
    if max_value != 255:
        raise ValueError("Only max_value 255 PPM files are supported")
    while data[idx:idx + 1].isspace():
        idx += 1
    raw = data[idx:]
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    if len(pixels) != width * height:
        raise ValueError(f"{path} pixel count mismatch")
    return width, height, pixels


def read_image(path: Path) -> tuple[int, int, list[Pixel]]:
    if path.suffix.lower() == ".ppm":
        return read_ppm(path)
    try:
        from PIL import Image  # type: ignore
    except ModuleNotFoundError as exc:
        raise ValueError(f"{path} requires Pillow for non-PPM image decoding") from exc
    image = Image.open(path).convert("RGB")
    width, height = image.size
    return width, height, list(image.getdata())


def write_ppm(path: Path, width: int, height: int, pixels: Iterable[Pixel]) -> None:
    body = bytearray()
    for red, green, blue in pixels:
        body.extend((red, green, blue))
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(body))


def compare(a_path: Path, b_path: Path, threshold: float, diff_path: Path | None) -> dict[str, object]:
    width_a, height_a, pixels_a = read_image(a_path)
    width_b, height_b, pixels_b = read_image(b_path)
    if (width_a, height_a) != (width_b, height_b):
        raise ValueError(f"Image dimensions differ: {width_a}x{height_a} vs {width_b}x{height_b}")
    changed = 0
    total_delta = 0
    max_delta = 0
    diff_pixels: list[Pixel] = []
    for left, right in zip(pixels_a, pixels_b):
        delta = sum(abs(x - y) for x, y in zip(left, right))
        if delta:
            changed += 1
        total_delta += delta
        max_delta = max(max_delta, delta)
        diff_pixels.append((min(255, delta), 0, 0) if delta else (0, 0, 0))
    total = width_a * height_a
    changed_ratio = changed / total if total else 0.0
    mae = total_delta / (total * 3 * 255) if total else 0.0
    if diff_path:
        write_ppm(diff_path, width_a, height_a, diff_pixels)
    return {
        "width": width_a,
        "height": height_a,
        "changed_pixels": changed,
        "total_pixels": total,
        "changed_ratio": changed_ratio,
        "mae": mae,
        "max_delta": max_delta,
        "threshold": threshold,
        "passed": changed_ratio <= threshold,
        "diff_path": str(diff_path) if diff_path else None,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / "a.ppm"
        b = root / "b.ppm"
        write_ppm(a, 2, 1, [(0, 0, 0), (255, 255, 255)])
        write_ppm(b, 2, 1, [(0, 0, 0), (255, 0, 255)])
        result = compare(a, b, threshold=0.5, diff_path=root / "diff.ppm")
        if not result["passed"] or result["changed_pixels"] != 1:
            raise AssertionError(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", nargs="?")
    parser.add_argument("actual", nargs="?")
    parser.add_argument("--threshold", type=float, default=0.01)
    parser.add_argument("--diff", help="optional output diff PPM path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Pixel diff self-test passed.")
        return
    if not args.baseline or not args.actual:
        parser.print_help()
        return
    result = compare(Path(args.baseline), Path(args.actual), args.threshold, Path(args.diff) if args.diff else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
