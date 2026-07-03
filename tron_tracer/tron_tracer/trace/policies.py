"""Every tracing policy is a named, documented parameter (blueprint Sec 5.3).
Nothing here is a silent default buried in code -- each field is recorded
verbatim in the trace output JSON and must appear in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Method = Literal["fifo", "lifo"]
FeePolicy = Literal["fee_first", "fees_last"]


@dataclass(frozen=True)
class TracePolicy:
    method: Method = "fifo"

    # Within a single transaction that both moves value and burns a TRX
    # fee from the same address, which leg drains the TRX tranche book
    # first. Both legs draw from the same book at the same order_key
    # (block, tx_index, log_index); this setting only disambiguates their
    # relative order at that identical position. "fee_first" (default)
    # models the fee as unconditionally deducted before the value transfer
    # for accounting purposes. "fees_last" is the named alternative from
    # Sec 5.3 -- selecting it must be stated in the report.
    fee_policy: FeePolicy = "fee_first"

    # Amounts below this threshold are not traced further (terminal type
    # 'dust'); 0 means trace everything. Any nonzero value must appear in
    # the report (Sec 5.3).
    dust_threshold: int = 0

    # Maximum recursion depth for multi-hop tracing (Sec 5.2.5d).
    max_hop_depth: int = 25

    # How a partially-marked tranche's "traced share" is carried forward
    # into each downstream consumption slice when that tranche is later
    # split across multiple outbound transactions. This is a judgment
    # call not spelled out verbatim in the blueprint: the underlying
    # FIFO/LIFO consumption ledger is always exact-integer chain
    # accounting; only the human-readable "how much of this hop derives
    # from the origin" figure uses proportional allocation, computed with
    # exact integer floor-division plus a final-slice remainder sweep so
    # the marked total across a tranche's full lifetime is always exact
    # (never drifts due to rounding). See METHODOLOGY.md Sec on
    # commingled-tranche attribution.
    partial_tranche_marking: Literal["proportional"] = "proportional"

    methodology_version: str = "1.0.0"

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "fee_policy": self.fee_policy,
            "dust_threshold": self.dust_threshold,
            "max_hop_depth": self.max_hop_depth,
            "partial_tranche_marking": self.partial_tranche_marking,
            "ordering": "block_number,tx_index,log_index",
            "self_transfer_handling": "tranche_identity_preserved",
            "rounding": "none_integer_only",
            "methodology_version": self.methodology_version,
        }
