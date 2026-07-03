"""Tier 3 behavioral signals (blueprint Sec 6.1 table). Each is weak
alone and combined multiplicatively in scoring.py. The blueprint leaves
exact detection thresholds as an implementation choice -- each is stated
explicitly here (not buried) so a report can cite exactly what rule
fired, and the thresholds are named constants so they can be tuned per
case without touching the detection logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from tron_tracer.trace.tranche import TransferRecord

SIGNAL_WEIGHTS = {
    "recurring_resource_topups": 0.35,
    "full_balance_sweeps": 0.30,
    "high_bidirectional_frequency": 0.25,
    "temporal_correlation": 0.15,  # supporting only -- see scoring.py
    "shared_rare_counterparties": 0.15,
    "sequential_activation_chain": 0.20,
}

GAS_TOPUP_MAX_SUN = 100 * 1_000_000  # <=100 TRX treated as a "top-up" not a real payment
GAS_TOPUP_MIN_OCCURRENCES = 3
SWEEP_MIN_FRACTION = 95  # percent of cumulative inbound-to-date
SWEEP_MIN_OCCURRENCES = 2
BIDIRECTIONAL_MIN_TX = 6
BIDIRECTIONAL_MAX_OVERLAP_JACCARD = 0.2
RARE_COUNTERPARTY_TOP_N_EXCLUDE = 50
ACTIVATION_CHAIN_MAX_BLOCK_SPAN = 100


@dataclass
class SignalResult:
    name: str
    present: bool
    weight: float
    evidence: list[str]  # tx hashes


def detect_recurring_resource_topups(a_to_b: list[TransferRecord], b_outbound: list[TransferRecord]) -> SignalResult:
    """A repeatedly sends small TRX amounts to B, each followed (at a
    later order_key) by B transacting outward -- the classic
    gas/energy-funding controller pattern. Rental services are excluded
    upstream via the label whitelist before this signal is even
    evaluated for a candidate pair (Sec 6.1)."""
    topups = sorted(
        [t for t in a_to_b if t.asset_id == "TRX" and t.amount <= GAS_TOPUP_MAX_SUN],
        key=lambda t: t.order_key,
    )
    b_outbound_sorted = sorted(b_outbound, key=lambda t: t.order_key)
    hits = []
    for topup in topups:
        if any(o.order_key > topup.order_key for o in b_outbound_sorted):
            hits.append(topup.tx_hash)
    present = len(hits) >= GAS_TOPUP_MIN_OCCURRENCES
    return SignalResult("recurring_resource_topups", present,
                         SIGNAL_WEIGHTS["recurring_resource_topups"] if present else 0.0, hits)


def detect_full_balance_sweeps(b_inbound: list[TransferRecord], b_outbound: list[TransferRecord]) -> SignalResult:
    """B repeatedly sweeps ~all of its accumulated balance out in a single
    transaction -- the deposit-address consolidation pattern."""
    inbound_sorted = sorted(b_inbound, key=lambda t: t.order_key)
    outbound_sorted = sorted(b_outbound, key=lambda t: t.order_key)
    hits = []
    for out in outbound_sorted:
        cumulative_in = sum(t.amount for t in inbound_sorted if t.order_key <= out.order_key)
        cumulative_out_before = sum(t.amount for t in outbound_sorted if t.order_key < out.order_key)
        available = cumulative_in - cumulative_out_before
        if available > 0 and out.amount * 100 >= SWEEP_MIN_FRACTION * available:
            hits.append(out.tx_hash)
    present = len(hits) >= SWEEP_MIN_OCCURRENCES
    return SignalResult("full_balance_sweeps", present,
                         SIGNAL_WEIGHTS["full_balance_sweeps"] if present else 0.0, hits)


def detect_high_bidirectional_frequency(
    a_to_b: list[TransferRecord], b_to_a: list[TransferRecord],
    a_other_counterparties: set[str], b_other_counterparties: set[str],
) -> SignalResult:
    tx_count = len(a_to_b) + len(b_to_a)
    union = a_other_counterparties | b_other_counterparties
    overlap = len(a_other_counterparties & b_other_counterparties) / len(union) if union else 0.0
    present = tx_count >= BIDIRECTIONAL_MIN_TX and overlap <= BIDIRECTIONAL_MAX_OVERLAP_JACCARD
    evidence = [t.tx_hash for t in (a_to_b + b_to_a)]
    return SignalResult("high_bidirectional_frequency", present,
                         SIGNAL_WEIGHTS["high_bidirectional_frequency"] if present else 0.0, evidence)


def detect_temporal_correlation(a_hour_histogram: list[int], b_hour_histogram: list[int]) -> SignalResult:
    """Cosine similarity of 24-bucket hour-of-day activity profiles.
    Supporting only -- scoring.py refuses to let this be the sole signal
    behind a link (Sec 6.1: 'supporting only, never load-bearing')."""
    if len(a_hour_histogram) != 24 or len(b_hour_histogram) != 24:
        raise ValueError("hour histograms must have 24 buckets")
    dot = sum(x * y for x, y in zip(a_hour_histogram, b_hour_histogram))
    norm_a = sum(x * x for x in a_hour_histogram) ** 0.5
    norm_b = sum(y * y for y in b_hour_histogram) ** 0.5
    similarity = dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
    present = similarity >= 0.8
    return SignalResult("temporal_correlation", present,
                         SIGNAL_WEIGHTS["temporal_correlation"] if present else 0.0, [])


def detect_shared_rare_counterparties(
    a_counterparties: set[str], b_counterparties: set[str], global_counterparty_rank: dict[str, int],
) -> SignalResult:
    """Shared counterparties excluding the top-N most globally common
    addresses (exchanges, popular contracts) which would otherwise
    dominate any two active addresses' overlap."""
    common = a_counterparties & b_counterparties
    rare_common = {
        c for c in common
        if global_counterparty_rank.get(c, RARE_COUNTERPARTY_TOP_N_EXCLUDE + 1) > RARE_COUNTERPARTY_TOP_N_EXCLUDE
    }
    present = len(rare_common) > 0
    return SignalResult("shared_rare_counterparties", present,
                         SIGNAL_WEIGHTS["shared_rare_counterparties"] if present else 0.0, sorted(rare_common))


def detect_sequential_activation_chain(chain: list[tuple[str, str, int]]) -> SignalResult:
    """chain: [(address, activated_by, activation_block), ...] ordered by
    activation_block. Present if consecutive activations occur within a
    short block span (peel-chain address-farming pattern)."""
    ordered = sorted(chain, key=lambda c: c[2])
    hits = []
    for i in range(1, len(ordered)):
        prev_addr, _prev_by, prev_block = ordered[i - 1]
        addr, activated_by, block = ordered[i]
        if activated_by == prev_addr and block - prev_block <= ACTIVATION_CHAIN_MAX_BLOCK_SPAN:
            hits.append(addr)
    present = len(hits) > 0
    return SignalResult("sequential_activation_chain", present,
                         SIGNAL_WEIGHTS["sequential_activation_chain"] if present else 0.0, hits)
