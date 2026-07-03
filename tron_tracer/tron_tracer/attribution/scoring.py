"""Composite confidence scoring (blueprint Sec 6.1):

    confidence = 1 - Prod(1 - w_i) over independent present signals,
    capped at 0.90 for anything without a Tier 1 signal.

Every link stores its full signal list with evidence transaction hashes
so the score is fully decomposable (Sec 6.1: "so the score is fully
decomposable on the stand").
"""

from __future__ import annotations

from dataclasses import dataclass

NO_TIER1_CAP = 0.90


@dataclass
class AttributionSignal:
    signal_type: str
    tier: int  # 1, 2, or 3
    weight: float
    evidence: list[str]
    supporting_only: bool = False  # e.g. temporal_correlation: never load-bearing alone


def compute_composite_confidence(signals: list[AttributionSignal]) -> tuple[float, list[dict]]:
    present = [s for s in signals if s.weight > 0]

    load_bearing_present = [s for s in present if not s.supporting_only]
    if not load_bearing_present:
        # A supporting-only signal (e.g. temporal correlation) can never
        # establish a link by itself.
        present = []

    has_tier1 = any(s.tier == 1 for s in present)

    product = 1.0
    for s in present:
        product *= (1 - s.weight)
    confidence = 1 - product

    if not has_tier1:
        confidence = min(confidence, NO_TIER1_CAP)

    confidence = round(confidence, 3)

    signal_records = [
        {"type": s.signal_type, "tier": s.tier, "weight": s.weight, "evidence": s.evidence,
         "supporting_only": s.supporting_only}
        for s in signals
    ]
    return confidence, signal_records
