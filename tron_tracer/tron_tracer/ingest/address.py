"""Tron base58check address encoding.

Raw `raw_data.contract[].parameter.value` fields in TronGrid's native
transaction JSON carry addresses in hex form (0x41-prefixed, 21 bytes).
Everywhere else in this codebase (transfers table, reports, trace
output) addresses are canonical base58 T-addresses, so all hex
addresses are converted at ingestion time -- never mixed downstream.
"""

from __future__ import annotations

import hashlib

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    num = int.from_bytes(data, "big")
    encoded = ""
    while num > 0:
        num, rem = divmod(num, 58)
        encoded = _ALPHABET[rem] + encoded
    n_pad = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_pad + encoded


def hex_to_base58(hex_address: str) -> str:
    """Convert a 41-prefixed hex Tron address to base58check (T...)."""
    hex_address = hex_address.strip()
    if hex_address.startswith("0x"):
        hex_address = hex_address[2:]
    raw = bytes.fromhex(hex_address)
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return _b58encode(raw + checksum)


def is_hex_address(value: str) -> bool:
    v = value[2:] if value.startswith("0x") else value
    if len(v) != 42 or not v.startswith("41"):
        return False
    try:
        int(v, 16)
        return True
    except ValueError:
        return False


def _b58decode(s: str) -> bytes:
    num = 0
    for ch in s:
        num = num * 58 + _ALPHABET.index(ch)
    n_pad = len(s) - len(s.lstrip("1"))
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * n_pad + raw


def base58_to_hex(base58_address: str) -> str:
    """Convert a base58check T-address to its 41-prefixed hex form,
    verifying the embedded checksum."""
    raw = _b58decode(base58_address)
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise ValueError(f"invalid base58check checksum for address {base58_address!r}")
    return payload.hex()


def normalize_address(value: str) -> str:
    """Return a base58 T-address regardless of whether `value` is already
    base58 or is a raw hex address."""
    if is_hex_address(value):
        return hex_to_base58(value)
    return value
