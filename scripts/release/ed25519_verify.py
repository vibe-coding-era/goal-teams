#!/usr/bin/env python3
"""Small dependency-free strict Ed25519 verifier for release receipts.

The release engine only needs verification. Signing remains in the
repository-external trusted host and uses its pinned ``cryptography`` runtime.
"""

from __future__ import annotations

import hashlib


_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_IDENTITY = (0, 1, 1, 0)


def _recover_x(y: int, sign: int) -> int:
    if y >= _Q:
        raise ValueError("non-canonical Ed25519 point")
    y2 = y * y % _Q
    x2 = (y2 - 1) * pow((_D * y2 + 1) % _Q, _Q - 2, _Q) % _Q
    x = pow(x2, (_Q + 3) // 8, _Q)
    if (x * x - x2) % _Q:
        x = x * _I % _Q
    if (x * x - x2) % _Q:
        raise ValueError("invalid Ed25519 point")
    if x == 0 and sign:
        raise ValueError("invalid Ed25519 sign bit")
    if (x & 1) != sign:
        x = _Q - x
    return x


def _decode_point(encoded: bytes) -> tuple[int, int, int, int]:
    if len(encoded) != 32:
        raise ValueError("Ed25519 points are 32 bytes")
    value = int.from_bytes(encoded, "little")
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, value >> 255)
    return (x, y, 1, x * y % _Q)


def _encode_point(point: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, _Q - 2, _Q)
    affine_x = x * inverse % _Q
    affine_y = y * inverse % _Q
    return (affine_y | ((affine_x & 1) << 255)).to_bytes(32, "little")


def _add(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = left
    x2, y2, z2, t2 = right
    a = (y1 - x1) * (y2 - x2) % _Q
    b = (y1 + x1) * (y2 + x2) % _Q
    c = 2 * _D * t1 * t2 % _Q
    d = 2 * z1 * z2 % _Q
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % _Q, g * h % _Q, f * g % _Q, e * h % _Q)


def _scalar_mult(
    point: tuple[int, int, int, int], scalar: int
) -> tuple[int, int, int, int]:
    result = _IDENTITY
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


_BASE = _decode_point(bytes.fromhex("5866666666666666666666666666666666666666666666666666666666666666"))


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return whether ``signature`` is a strict Ed25519 signature of ``message``."""

    if len(public_key) != 32 or len(signature) != 64:
        return False
    encoded_r = signature[:32]
    scalar_s = int.from_bytes(signature[32:], "little")
    if scalar_s >= _L:
        return False
    try:
        point_a = _decode_point(public_key)
        point_r = _decode_point(encoded_r)
    except ValueError:
        return False
    # Require the prime-order subgroup and reject its identity.
    encoded_identity = _encode_point(_IDENTITY)
    if (
        _encode_point(_scalar_mult(point_a, _L)) != encoded_identity
        or _encode_point(_scalar_mult(point_r, _L)) != encoded_identity
        or _encode_point(point_a) == encoded_identity
        or _encode_point(point_r) == encoded_identity
    ):
        return False
    challenge = int.from_bytes(
        hashlib.sha512(encoded_r + public_key + message).digest(), "little"
    ) % _L
    left = _scalar_mult(_BASE, scalar_s)
    right = _add(point_r, _scalar_mult(point_a, challenge))
    return _encode_point(left) == _encode_point(right)
