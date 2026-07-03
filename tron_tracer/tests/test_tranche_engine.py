"""Golden, hand-computed test cases for tranche accounting (blueprint
Sec 5.4). Each test's expected numbers are computed by hand in the
comments -- these are the exhibits a court could be walked through.
"""

import pytest

from tron_tracer.trace.policies import TracePolicy
from tron_tracer.trace.tranche import InvariantError, NEG_INF_ORDER_KEY, replay


ADDR = "TAddressUnderTest111111111111111111"
A = "TSenderA1111111111111111111111111111"
B = "TSenderB1111111111111111111111111111"
C = "TRecipientC111111111111111111111111"


def test_fifo_partial_split_and_divergence_from_lifo(xfer):
    # ADDR receives 100 (tx1) then 50 (tx2), then sends 120 out (tx3).
    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 100),
        xfer("tx2", 101, 0, B, ADDR, 50),
        xfer("tx3", 102, 0, ADDR, C, 120),
    ]

    fifo_book = replay(ADDR, "TRX", transfers, TracePolicy(method="fifo"))
    # FIFO: tx3 draws 100 from tx1 (fully) + 20 from tx2 (partial split).
    fifo_events = {(e.tranche_id, e.amount_consumed) for e in fifo_book.consumptions}
    fifo_amounts_by_source = {
        fifo_book.tranches[tid].source_tx: amt for tid, amt in fifo_events
    }
    assert fifo_amounts_by_source == {"tx1": 100, "tx2": 20}
    remaining = [t for t in fifo_book.tranches.values() if t.amount_remaining > 0]
    assert len(remaining) == 1
    assert remaining[0].source_tx == "tx2" and remaining[0].amount_remaining == 30

    lifo_book = replay(ADDR, "TRX", transfers, TracePolicy(method="lifo"))
    # LIFO: tx3 draws 50 from tx2 (fully) + 70 from tx1 (partial split).
    lifo_events = {(e.tranche_id, e.amount_consumed) for e in lifo_book.consumptions}
    lifo_amounts_by_source = {
        lifo_book.tranches[tid].source_tx: amt for tid, amt in lifo_events
    }
    assert lifo_amounts_by_source == {"tx2": 50, "tx1": 70}
    remaining = [t for t in lifo_book.tranches.values() if t.amount_remaining > 0]
    assert len(remaining) == 1
    assert remaining[0].source_tx == "tx1" and remaining[0].amount_remaining == 30

    # Total traced value is conserved regardless of method (Sec 5.4 invariant 4).
    assert sum(a for a in fifo_amounts_by_source.values()) == sum(a for a in lifo_amounts_by_source.values()) == 120


def test_same_block_ordering_no_future_bleed(xfer):
    # Two inbounds in the same block at different tx_index; an outbound
    # sandwiched between them must only see the earlier one.
    transfers = [
        xfer("txA", 100, 0, A, ADDR, 100),
        xfer("txB", 100, 2, B, ADDR, 50),
        xfer("txC", 100, 1, ADDR, C, 120),  # tx_index=1: only txA (index 0) exists yet
    ]
    with pytest.raises(InvariantError):
        replay(ADDR, "TRX", transfers, TracePolicy(method="fifo"))

    # Reduce to an amount coverable by txA alone -- must succeed, and the
    # later txB inbound must remain untouched by this consumption.
    transfers_ok = [
        xfer("txA", 100, 0, A, ADDR, 100),
        xfer("txB", 100, 2, B, ADDR, 50),
        xfer("txC", 100, 1, ADDR, C, 100),
    ]
    book = replay(ADDR, "TRX", transfers_ok, TracePolicy(method="fifo"))
    assert len(book.consumptions) == 1
    assert book.consumptions[0].amount_consumed == 100
    tranB = next(t for t in book.tranches.values() if t.source_tx == "txB")
    assert tranB.amount_remaining == 50  # untouched


def test_fee_policy_fee_first_vs_fees_last(xfer):
    # Two tranches: a small one (5,000) from tx1 and a large one
    # (1,000,000) from tx2. A single outbound tx3 moves 600,000 to C and
    # burns a 10,000 sun fee. Aggregate remaining on tx2's tranche is
    # identical either way (605,000 consumed total), but WHICH dollars
    # are attributed to the fee vs. the real recipient differs -- exactly
    # the evidentiary distinction Sec 5.3 requires be stated in reports.
    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 5_000),
        xfer("tx2", 101, 0, B, ADDR, 1_000_000),
        xfer("tx3", 102, 0, ADDR, C, 600_000, fee_sun=10_000),
    ]

    fee_first = replay(ADDR, "TRX", transfers, TracePolicy(method="fifo", fee_policy="fee_first"))
    by_kind_source = {
        (fee_first.tranches[e.tranche_id].source_tx, e.kind): e.amount_consumed
        for e in fee_first.consumptions
    }
    # fee_first: fee (10,000) drains tx1 (5,000) then tx2 (5,000); value
    # (600,000) drains entirely from tx2.
    assert by_kind_source == {("tx1", "fee_burn"): 5_000, ("tx2", "fee_burn"): 5_000, ("tx2", "transfer"): 600_000}
    tx2_remaining = next(t for t in fee_first.tranches.values() if t.source_tx == "tx2").amount_remaining
    assert tx2_remaining == 1_000_000 - 5_000 - 600_000 == 395_000

    fees_last = replay(ADDR, "TRX", transfers, TracePolicy(method="fifo", fee_policy="fees_last"))
    by_kind_source = {
        (fees_last.tranches[e.tranche_id].source_tx, e.kind): e.amount_consumed
        for e in fees_last.consumptions
    }
    # fees_last: value (600,000) drains tx1 (5,000) then tx2 (595,000);
    # fee (10,000) drains entirely from tx2.
    assert by_kind_source == {("tx1", "transfer"): 5_000, ("tx2", "transfer"): 595_000, ("tx2", "fee_burn"): 10_000}
    tx2_remaining = next(t for t in fees_last.tranches.values() if t.source_tx == "tx2").amount_remaining
    assert tx2_remaining == 395_000  # same aggregate remaining, different attribution


def test_pre_window_balance_synthetic_tranche(xfer):
    transfers = [xfer("tx1", 100, 0, ADDR, C, 300)]
    book = replay(ADDR, "TRX", transfers, TracePolicy(method="fifo"), opening_balance=500)
    unknown = next(t for t in book.tranches.values() if t.source_tx == "unknown_origin")
    assert unknown.order_key == NEG_INF_ORDER_KEY
    assert unknown.amount_original == 500
    assert unknown.amount_remaining == 200  # 500 - 300 consumed
    assert book.consumptions[0].tranche_id == unknown.tranche_id


def test_self_transfer_preserves_tranche_identity_fifo(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 1_000),
        xfer("tx_self", 101, 0, ADDR, ADDR, 400),  # self-transfer
        xfer("tx_out", 102, 0, ADDR, C, 400),
    ]
    book = replay(ADDR, "TRX", transfers, TracePolicy(method="fifo"))

    self_events = [e for e in book.consumptions if e.kind == "self_transfer"]
    assert len(self_events) == 1
    original = book.tranches[self_events[0].tranche_id]
    assert original.source_tx == "tx1"

    replacement = next(t for t in book.tranches.values() if t.parent_tranche_id == original.tranche_id)
    assert replacement.order_key == (100, 0, 0)  # identity preserved, NOT (101, 0, 0)
    assert replacement.source_tx == "tx1"
    assert replacement.pass_through_txs == ("tx_self",)
    assert replacement.amount_original == 400

    # Final outbound of 400 under FIFO: original tranche (lower sequence
    # id, tie-broken ahead of the same-order_key replacement) is drained
    # first per the documented tie-break rule.
    final_event = book.consumptions[-1]
    assert book.tranches[final_event.tranche_id].tranche_id == original.tranche_id
    assert original.amount_remaining == 200  # 1000 - 400 (self) - 400 (final out)
    assert replacement.amount_remaining == 400  # untouched


def test_conservation_invariant_holds_across_methods(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 1_000),
        xfer("tx2", 101, 0, ADDR, C, 300),
        xfer("tx3", 102, 0, B, ADDR, 500),
        xfer("tx4", 103, 0, ADDR, C, 700),
    ]
    for method in ("fifo", "lifo"):
        book = replay(ADDR, "TRX", transfers, TracePolicy(method=method))
        book.conservation_check()  # raises on failure; explicit call here for clarity


def test_determinism_identical_hash_on_rerun(xfer):
    from tron_tracer.trace.canonical import canonical_sha256

    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 1_000),
        xfer("tx2", 101, 0, B, ADDR, 500),
        xfer("tx3", 102, 0, ADDR, C, 900),
    ]
    shuffled = [transfers[2], transfers[0], transfers[1]]  # input order must not matter

    def digest(order):
        book = replay(ADDR, "TRX", order, TracePolicy(method="fifo"))
        doc = {
            "tranches": sorted((t.to_canonical() for t in book.tranches.values()), key=lambda d: d["tranche_id"]),
            "consumptions": [e.to_canonical() for e in book.consumptions],
        }
        return canonical_sha256(doc)

    assert digest(transfers) == digest(shuffled)


def test_underflow_raises_invariant_error(xfer):
    transfers = [
        xfer("tx1", 100, 0, A, ADDR, 100),
        xfer("tx2", 101, 0, ADDR, C, 150),  # more than was ever received
    ]
    with pytest.raises(InvariantError):
        replay(ADDR, "TRX", transfers, TracePolicy(method="fifo"))
