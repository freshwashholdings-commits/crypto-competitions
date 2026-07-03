"""Multi-hop tracing (blueprint Sec 5.2). Builds a directed trace graph by
repeatedly applying single-address tranche accounting (tranche.py) and
following marked (traced) amounts across the consumption ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tron_tracer.config import TRX_ASSET_ID
from tron_tracer.trace.canonical import canonical_sha256
from tron_tracer.trace.policies import TracePolicy
from tron_tracer.trace.tranche import FEE_BURN_SINK, TransferRecord, UNKNOWN_ORIGIN_TX, replay

TerminalType = str  # 'service' | 'contract_interaction' | 'dust' | 'holding' | 'max_hop_depth' | 'fee_burn' | 'pre_window_unknown'


class TransferProvider(Protocol):
    def transfers_touching(self, address: str) -> list[TransferRecord]: ...

    def is_labeled_service(self, address: str) -> bool: ...

    def is_contract(self, address: str) -> bool: ...

    def opening_balance(self, address: str, asset_id: str) -> int:
        return 0

    def transfer_by_tx(self, tx_hash: str, asset_id: str) -> TransferRecord | None: ...


class InMemoryProvider:
    """TransferProvider backed by a flat in-memory transfer list -- used
    for tests and small ad-hoc traces."""

    def __init__(self, transfers: list[TransferRecord], labeled: set[str] = frozenset(),
                 contracts: set[str] = frozenset(), openings: dict[tuple[str, str], int] | None = None):
        self._transfers = transfers
        self._labeled = set(labeled)
        self._contracts = set(contracts)
        self._openings = openings or {}

    def transfers_touching(self, address: str) -> list[TransferRecord]:
        return [t for t in self._transfers if t.from_address == address or t.to_address == address]

    def is_labeled_service(self, address: str) -> bool:
        return address in self._labeled

    def is_contract(self, address: str) -> bool:
        return address in self._contracts

    def opening_balance(self, address: str, asset_id: str) -> int:
        return self._openings.get((address, asset_id), 0)

    def transfer_by_tx(self, tx_hash: str, asset_id: str) -> TransferRecord | None:
        for t in self._transfers:
            if t.tx_hash == tx_hash and t.asset_id == asset_id:
                return t
        return None


@dataclass
class Terminal:
    terminal_type: TerminalType
    address: str | None
    amount: int
    hop: int
    tx_hash: str | None = None

    def to_canonical(self) -> dict:
        return {
            "terminal_type": self.terminal_type,
            "address": self.address,
            "amount": self.amount,
            "hop": self.hop,
            "tx_hash": self.tx_hash,
        }


@dataclass
class HopResult:
    hop: int
    address: str
    tranches: list[dict]
    consumptions: list[dict]

    def to_canonical(self) -> dict:
        return {"hop": self.hop, "address": self.address, "tranches": self.tranches, "consumptions": self.consumptions}


@dataclass
class TraceRun:
    parameters: dict
    hops: list[HopResult] = field(default_factory=list)
    terminals: list[Terminal] = field(default_factory=list)

    def to_canonical(self, methodology_version: str, data_snapshot_block: int | None) -> dict:
        terminal_summary: dict[str, int] = {}
        for t in self.terminals:
            terminal_summary[t.terminal_type] = terminal_summary.get(t.terminal_type, 0) + t.amount
        doc = {
            "schema_version": "1.0",
            "methodology_version": methodology_version,
            "data_snapshot_block": data_snapshot_block,
            "parameters": self.parameters,
            "hops": [h.to_canonical() for h in self.hops],
            "terminals": [t.to_canonical() for t in self.terminals],
            "terminal_summary": terminal_summary,
            "total_traced": sum(terminal_summary.values()),
        }
        doc["document_sha256"] = canonical_sha256(doc)
        return doc


def run_forward_trace(
    start_address: str,
    asset_id: str,
    provider: TransferProvider,
    policy: TracePolicy,
    seed_tx_hashes: list[str] | None = None,
    data_snapshot_block: int | None = None,
) -> dict:
    """Forward trace: follow marked (traced) funds outward from the start
    address through every consuming hop (blueprint Sec 5.2 steps 1-3)."""
    parameters = {
        "start_address": start_address, "asset_id": asset_id, "direction": "forward",
        "seed_tx_hashes": sorted(seed_tx_hashes) if seed_tx_hashes else "all",
        "policy": policy.as_dict(),
    }
    run = TraceRun(parameters=parameters)

    # frontier item: (address, hop, {(tx_hash, log_index): marked_amount})
    seed_book = replay(
        start_address, asset_id, provider.transfers_touching(start_address), policy,
        opening_balance=provider.opening_balance(start_address, asset_id),
        opening_balance_marked=not seed_tx_hashes,
    )
    if seed_tx_hashes:
        seed_marks: dict[tuple[str, int], int] = {}
        for t in seed_book.tranches.values():
            if t.source_tx in seed_tx_hashes:
                seed_marks[(t.source_tx, t.order_key[2])] = t.amount_original
    else:
        seed_marks = None  # "all": opening balance + every inbound tranche fully marked

    frontier: list[tuple[str, int, dict[tuple[str, int], int]]] = [(start_address, 0, seed_marks or {"__all__": 0})]
    visited_hops = 0

    while frontier:
        address, hop, marks = frontier.pop(0)
        visited_hops += 1

        mark_all = "__all__" in marks
        book = replay(
            address, asset_id, provider.transfers_touching(address), policy,
            opening_balance=provider.opening_balance(address, asset_id),
            opening_balance_marked=mark_all,
            marked_seed=None if mark_all else marks,
        )
        if mark_all:
            for t in book.tranches.values():
                if t.source_tx != UNKNOWN_ORIGIN_TX:
                    t.marked_amount_original = t.amount_original
                    t.marked_amount_remaining = t.amount_original
            # Re-run consumption bookkeeping isn't needed: marks are set
            # before any consumption only for the very first (hop 0, "all")
            # book, since frontier items after hop 0 always carry explicit
            # marks. Guard this assumption:
            assert hop == 0, "mark_all is only valid as the trace seed"

        run.hops.append(HopResult(
            hop=hop, address=address,
            tranches=[t.to_canonical() for t in sorted(book.tranches.values(), key=lambda t: t.tranche_id)],
            consumptions=[e.to_canonical() for e in book.consumptions],
        ))

        # Holding: whatever marked amount never got consumed further.
        holding = sum(t.marked_amount_remaining for t in book.tranches.values())
        if holding > 0:
            run.terminals.append(Terminal("holding", address, holding, hop))

        # Aggregate marked consumption by destination tx (accumulates
        # multiple source tranches funding the same outbound tx).
        next_marks: dict[str, dict[tuple[str, int], int]] = {}
        for e in book.consumptions:
            if e.marked_amount_consumed <= 0:
                continue
            if e.kind == "fee_burn":
                run.terminals.append(Terminal("fee_burn", FEE_BURN_SINK, e.marked_amount_consumed, hop, e.outbound_tx))
                continue
            if e.kind == "self_transfer":
                continue  # stays in this same book via the replacement tranche; not a new hop
            dest = e.to_address
            log_index = e.outbound_order_key[2]
            next_marks.setdefault(dest, {})
            key = (e.outbound_tx, log_index)
            next_marks[dest][key] = next_marks[dest].get(key, 0) + e.marked_amount_consumed

        for dest, dest_marks in sorted(next_marks.items()):
            amount = sum(dest_marks.values())
            if amount < policy.dust_threshold:
                run.terminals.append(Terminal("dust", dest, amount, hop))
                continue
            if provider.is_labeled_service(dest):
                run.terminals.append(Terminal("service", dest, amount, hop))
                continue
            if provider.is_contract(dest):
                run.terminals.append(Terminal("contract_interaction", dest, amount, hop))
                continue
            if hop + 1 > policy.max_hop_depth:
                run.terminals.append(Terminal("max_hop_depth", dest, amount, hop))
                continue
            frontier.append((dest, hop + 1, dest_marks))

    return run.to_canonical(policy.methodology_version, data_snapshot_block)


def run_backward_trace(
    start_address: str,
    asset_id: str,
    provider: TransferProvider,
    policy: TracePolicy,
    seed_outbound_tx: str | None = None,
    data_snapshot_block: int | None = None,
) -> dict:
    """Backward trace: attribute an outbound transfer (or current holding)
    back through the tranches that funded it (blueprint Sec 5.2 step 4).
    Recurses across addresses via each tranche's source_tx -- which,
    thanks to self-transfer lineage preservation (tranche.py), already
    points at the true originating inbound transfer even if the funds
    passed through self-transfers first."""
    parameters = {
        "start_address": start_address, "asset_id": asset_id, "direction": "backward",
        "seed_outbound_tx": seed_outbound_tx or "current_holding",
        "policy": policy.as_dict(),
    }
    run = TraceRun(parameters=parameters)

    # frontier item: (address, hop, [(source_tx, amount), ...]) to attribute
    seed_book = replay(
        start_address, asset_id, provider.transfers_touching(start_address), policy,
        opening_balance=provider.opening_balance(start_address, asset_id),
    )
    if seed_outbound_tx:
        seed_sources = [
            (seed_book.tranches[e.tranche_id].source_tx, e.amount_consumed)
            for e in seed_book.consumptions if e.outbound_tx == seed_outbound_tx
        ]
    else:
        seed_sources = [(t.source_tx, t.amount_remaining) for t in seed_book.tranches.values() if t.amount_remaining > 0]

    run.hops.append(HopResult(
        hop=0, address=start_address,
        tranches=[t.to_canonical() for t in sorted(seed_book.tranches.values(), key=lambda t: t.tranche_id)],
        consumptions=[e.to_canonical() for e in seed_book.consumptions],
    ))

    frontier: list[tuple[str, int, list[tuple[str, int]]]] = [(start_address, 0, seed_sources)]

    while frontier:
        address, hop, sources = frontier.pop(0)

        for source_tx, amount in sources:
            if amount <= 0:
                continue
            if source_tx == UNKNOWN_ORIGIN_TX:
                run.terminals.append(Terminal("pre_window_unknown", address, amount, hop))
                continue
            if amount < policy.dust_threshold:
                run.terminals.append(Terminal("dust", address, amount, hop))
                continue
            if hop + 1 > policy.max_hop_depth:
                run.terminals.append(Terminal("max_hop_depth", address, amount, hop))
                continue

            origin_transfer = provider.transfer_by_tx(source_tx, asset_id)
            if origin_transfer is None:
                run.terminals.append(Terminal("holding", address, amount, hop, source_tx))
                continue
            sender = origin_transfer.from_address
            if provider.is_labeled_service(sender):
                run.terminals.append(Terminal("service", sender, amount, hop + 1, source_tx))
                continue
            if provider.is_contract(sender):
                run.terminals.append(Terminal("contract_interaction", sender, amount, hop + 1, source_tx))
                continue

            sender_book = replay(
                sender, asset_id, provider.transfers_touching(sender), policy,
                opening_balance=provider.opening_balance(sender, asset_id),
            )
            run.hops.append(HopResult(
                hop=hop + 1, address=sender,
                tranches=[t.to_canonical() for t in sorted(sender_book.tranches.values(), key=lambda t: t.tranche_id)],
                consumptions=[e.to_canonical() for e in sender_book.consumptions],
            ))
            matching_events = [
                e for e in sender_book.consumptions if e.outbound_tx == source_tx and e.kind != "fee_burn"
            ]
            if not matching_events:
                run.terminals.append(Terminal("holding", sender, amount, hop + 1, source_tx))
                continue

            # `amount` here may be only a fraction of what sender.tx really
            # moved (e.g. an intermediate hop only forwarded part of it
            # onward). Scale sender's own consumption breakdown down to
            # that same fraction, integer-exact via floor + a
            # remainder-sweep on the last slice (same technique as
            # tranche.py's marked-amount propagation).
            total_matched = sum(e.amount_consumed for e in matching_events)
            next_sources: list[tuple[str, int]] = []
            allocated = 0
            for i, e in enumerate(matching_events):
                if i == len(matching_events) - 1:
                    scaled = amount - allocated
                else:
                    scaled = (e.amount_consumed * amount) // total_matched
                    allocated += scaled
                next_sources.append((sender_book.tranches[e.tranche_id].source_tx, scaled))
            frontier.append((sender, hop + 1, next_sources))

    return run.to_canonical(policy.methodology_version, data_snapshot_block)
