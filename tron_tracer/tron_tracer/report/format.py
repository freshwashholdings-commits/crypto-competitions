"""Decimal formatting -- display layer ONLY (blueprint Sec 1.2). All
tracing logic upstream of this module stays integer-only; `Decimal` is
used here purely for human-readable rendering, never for computation
that feeds back into the ledger."""

from __future__ import annotations

from decimal import Decimal

from tron_tracer.config import SUN_PER_TRX, TRX_ASSET_ID, USDT_TRC20_CONTRACT, USDT_TRC20_DECIMALS

KNOWN_DECIMALS = {
    TRX_ASSET_ID: 6,
    USDT_TRC20_CONTRACT: USDT_TRC20_DECIMALS,
}


def format_amount(amount: int, asset_id: str, decimals: int | None = None) -> str:
    d = decimals if decimals is not None else KNOWN_DECIMALS.get(asset_id, 0)
    if d == 0:
        return f"{amount} (raw units)"
    value = Decimal(amount) / (Decimal(10) ** d)
    return f"{value.normalize() if value == value.to_integral() else value}"
