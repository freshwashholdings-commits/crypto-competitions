"""Tranche accounting (blueprint Sec 5.1, 5.3, 5.4). This is the
evidentiary core of the whole tool: every function here is pure,
integer-only, and deterministic given its inputs.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from tron_tracer.config import TRX_ASSET_ID
from tron_tracer.trace.policies import TracePolicy

OrderKey = tuple[int, int, int]

# Sentinel strictly less than every real order_key. Real block numbers are
# always >= 0 on-chain; -1 guarantees ordering even against block 0.
NEG_INF_ORDER_KEY: OrderKey = (-1, -1, -1)
UNKNOWN_ORIGIN_TX = "unknown_origin"
FEE_BURN_SINK = "__fee_burn__"


class InvariantError(RuntimeError):
    """Raised when a runtime assertion from blueprint Sec 5.4 fails."""


@dataclass
class TransferRecord:
    """Engine-facing transfer representation, decoupled from the ORM so
    the engine is testable with plain fixtures (Sec 5.4 golden tests)."""

    tx_hash: str
    block_number: int
    tx_index: int
    log_index: int
    block_timestamp: int
    from_address: str
    to_address: str
    asset_type: str
    asset_id: str
    amount: int
    fee_sun: int = 0
    contract_type: str | None = None

    @property
    def order_key(self) -> OrderKey:
        return (self.block_number, self.tx_index, self.log_index)


@dataclass
class Tranche:
    tranche_id: str
    source_tx: str
    order_key: OrderKey
    amount_original: int
    amount_remaining: int
    marked_amount_original: int = 0
    marked_amount_remaining: int = 0
    pass_through_txs: tuple[str, ...] = ()
    parent_tranche_id: str | None = None

    def to_canonical(self) -> dict:
        return {
            "tranche_id": self.tranche_id,
            "source_tx": self.source_tx,
            "order_key": list(self.order_key),
            "amount_original": self.amount_original,
            "marked_amount_original": self.marked_amount_original,
            "pass_through_txs": list(self.pass_through_txs),
            "parent_tranche_id": self.parent_tranche_id,
        }


@dataclass
class ConsumptionEvent:
    outbound_tx: str
    outbound_order_key: OrderKey
    tranche_id: str
    amount_consumed: int
    marked_amount_consumed: int
    to_address: str
    kind: str  # "transfer" | "self_transfer" | "fee_burn"

    def to_canonical(self) -> dict:
        return {
            "outbound_tx": self.outbound_tx,
            "outbound_order_key": list(self.outbound_order_key),
            "tranche_id": self.tranche_id,
            "amount_consumed": self.amount_consumed,
            "marked_amount_consumed": self.marked_amount_consumed,
            "to_address": self.to_address,
            "kind": self.kind,
        }


class TrancheBook:
    """FIFO or LIFO tranche accounting for one (address, asset) pair."""

    def __init__(self, address: str, asset_id: str, policy: TracePolicy):
        self.address = address
        self.asset_id = asset_id
        self.policy = policy
        self.tranches: dict[str, Tranche] = {}
        self.consumptions: list[ConsumptionEvent] = []
        self._active: list[tuple[OrderKey, str]] = []  # sorted ascending by (order_key, tranche_id)
        self._seq = 0

    # -- construction -----------------------------------------------------

    def _next_id(self) -> str:
        self._seq += 1
        return f"{self.address}:{self.asset_id}:T{self._seq:08d}"

    def _add_tranche(self, tranche: Tranche) -> None:
        self.tranches[tranche.tranche_id] = tranche
        bisect.insort(self._active, (tranche.order_key, tranche.tranche_id))

    def open_pre_window_balance(self, amount: int, *, marked: bool = False) -> None:
        """Synthetic tranche for balance carried in from before the replay
        window (blueprint Sec 5.3 'pre-window balance' policy)."""
        if amount <= 0:
            return
        marked_amount = amount if marked else 0
        tranche = Tranche(
            tranche_id=self._next_id(),
            source_tx=UNKNOWN_ORIGIN_TX,
            order_key=NEG_INF_ORDER_KEY,
            amount_original=amount,
            amount_remaining=amount,
            marked_amount_original=marked_amount,
            marked_amount_remaining=marked_amount,
        )
        self._add_tranche(tranche)

    def process_inbound(self, transfer: TransferRecord, *, marked_amount: int = 0) -> Tranche:
        if transfer.to_address != self.address or transfer.asset_id != self.asset_id:
            raise ValueError("inbound transfer does not target this book's (address, asset)")
        if marked_amount > transfer.amount:
            raise ValueError("marked_amount cannot exceed transfer amount")
        tranche = Tranche(
            tranche_id=self._next_id(),
            source_tx=transfer.tx_hash,
            order_key=transfer.order_key,
            amount_original=transfer.amount,
            amount_remaining=transfer.amount,
            marked_amount_original=marked_amount,
            marked_amount_remaining=marked_amount,
        )
        self._add_tranche(tranche)
        return tranche

    # -- consumption --------------------------------------------------------

    def process_outbound(self, transfer: TransferRecord) -> list[ConsumptionEvent]:
        if transfer.from_address != self.address or transfer.asset_id != self.asset_id:
            raise ValueError("outbound transfer does not originate from this book's (address, asset)")
        is_self = transfer.from_address == transfer.to_address
        kind = "self_transfer" if is_self else "transfer"
        events, replacements = self._consume(transfer.amount, transfer, kind, transfer.to_address, is_self)
        for r in replacements:
            self._add_tranche(r)
        return events

    def process_fee(self, transfer: TransferRecord) -> list[ConsumptionEvent]:
        """Fee is always TRX-denominated regardless of the transfer's own
        asset -- only call this on the TRX book (Sec 5.3 fee policy)."""
        if self.asset_id != TRX_ASSET_ID:
            raise ValueError("fees are only consumed against the TRX tranche book")
        if transfer.from_address != self.address or transfer.fee_sun <= 0:
            return []
        events, replacements = self._consume(transfer.fee_sun, transfer, "fee_burn", FEE_BURN_SINK, False)
        for r in replacements:
            self._add_tranche(r)
        return events

    def apply_transfer_leg(self, transfer: TransferRecord) -> list[ConsumptionEvent]:
        """Apply both the value leg (if this book is the transfer's asset)
        and the fee leg (if this book is the TRX book) for one outbound
        transfer, in the configured fee_policy order."""
        events: list[ConsumptionEvent] = []
        is_value_leg = transfer.from_address == self.address and transfer.asset_id == self.asset_id
        is_fee_leg = self.asset_id == TRX_ASSET_ID and transfer.from_address == self.address and transfer.fee_sun > 0

        if self.policy.fee_policy == "fee_first":
            if is_fee_leg:
                events += self.process_fee(transfer)
            if is_value_leg:
                events += self.process_outbound(transfer)
        else:  # fees_last
            if is_value_leg:
                events += self.process_outbound(transfer)
            if is_fee_leg:
                events += self.process_fee(transfer)
        return events

    def _consume(
        self, amount: int, transfer: TransferRecord, kind: str, to_address: str, preserve_lineage: bool
    ) -> tuple[list[ConsumptionEvent], list[Tranche]]:
        remaining_to_consume = amount
        events: list[ConsumptionEvent] = []
        replacements: list[Tranche] = []

        while remaining_to_consume > 0:
            if not self._active:
                raise InvariantError(
                    f"tranche underflow for {self.address}/{self.asset_id} at tx {transfer.tx_hash} "
                    f"({kind}): needed {remaining_to_consume} more but no tranches remain"
                )
            idx = 0 if self.policy.method == "fifo" else -1
            order_key, tranche_id = self._active[idx]
            if order_key > transfer.order_key:
                raise InvariantError(
                    f"no time travel: tranche {tranche_id} has order_key {order_key} > "
                    f"consuming transfer order_key {transfer.order_key}"
                )
            tranche = self.tranches[tranche_id]
            before_remaining = tranche.amount_remaining
            take = min(before_remaining, remaining_to_consume)
            tranche.amount_remaining -= take

            if tranche.amount_remaining == 0:
                marked_take = tranche.marked_amount_remaining  # sweep rounding remainder on final slice
            elif tranche.marked_amount_remaining > 0:
                marked_take = (tranche.marked_amount_remaining * take) // before_remaining
            else:
                marked_take = 0
            tranche.marked_amount_remaining -= marked_take

            events.append(ConsumptionEvent(
                outbound_tx=transfer.tx_hash,
                outbound_order_key=transfer.order_key,
                tranche_id=tranche.tranche_id,
                amount_consumed=take,
                marked_amount_consumed=marked_take,
                to_address=to_address,
                kind=kind,
            ))

            if preserve_lineage and take > 0:
                replacements.append(Tranche(
                    tranche_id=self._next_id(),
                    source_tx=tranche.source_tx,
                    order_key=tranche.order_key,  # identity preserved, not reset to this tx's position
                    amount_original=take,
                    amount_remaining=take,
                    marked_amount_original=marked_take,
                    marked_amount_remaining=marked_take,
                    pass_through_txs=tranche.pass_through_txs + (transfer.tx_hash,),
                    parent_tranche_id=tranche.tranche_id,
                ))

            if tranche.amount_remaining == 0:
                self._active.pop(idx)

            remaining_to_consume -= take

        return events, replacements

    # -- invariants (Sec 5.4) ------------------------------------------------

    def conservation_check(self) -> None:
        total_created = sum(t.amount_original for t in self.tranches.values())
        total_consumed = sum(e.amount_consumed for e in self.consumptions)
        total_remaining = sum(t.amount_remaining for t in self.tranches.values())
        if total_created - total_consumed != total_remaining:
            raise InvariantError(
                f"conservation violated for {self.address}/{self.asset_id}: "
                f"created={total_created} consumed={total_consumed} remaining={total_remaining}"
            )


def replay(
    address: str,
    asset_id: str,
    transfers: list[TransferRecord],
    policy: TracePolicy,
    *,
    opening_balance: int = 0,
    opening_balance_marked: bool = False,
    marked_seed: dict[tuple[str, int], int] | None = None,
) -> TrancheBook:
    """Replay every transfer touching `address` (any asset, so TRX fees on
    non-TRX transfers are captured) in canonical order, building the
    (address, asset_id) tranche book.

    marked_seed: optional {(tx_hash, log_index): marked_amount} for
    inbound transfers that seed a multi-hop trace (Sec 5.2), keyed by
    log_index too since a single tx can carry more than one inbound
    event to the same address. Absent/empty means a full, unmarked book
    (used for reconciliation or as a hop's "available liquidity"
    context).
    """
    marked_seed = marked_seed or {}
    book = TrancheBook(address, asset_id, policy)
    book.open_pre_window_balance(opening_balance, marked=opening_balance_marked)

    ordered = sorted(transfers, key=lambda t: (t.order_key, t.tx_hash, t.asset_id))
    for transfer in ordered:
        if transfer.to_address == address and transfer.asset_id == asset_id:
            marked_amount = marked_seed.get((transfer.tx_hash, transfer.log_index), 0)
            book.process_inbound(transfer, marked_amount=marked_amount)
        if transfer.from_address == address:
            events = book.apply_transfer_leg(transfer)
            book.consumptions.extend(events)

    book.conservation_check()
    return book
