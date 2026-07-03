# Tron Address Tracer & Analyzer — Methodology

**Version:** 1.0.0 (matches `tron_tracer.METHODOLOGY_VERSION`, recorded in every trace and attribution output document alongside the exact parameters used to produce it)

This document is the plain-English companion to the code. It exists so that a trace or
attribution result can be explained, cross-examined, and reproduced by someone with no
access to this repository — only the reproducibility bundle (`tron_tracer report generate
--bundle`) and this document. It follows the reliability factors that typically matter for
expert-evidence challenges: testability, known error rate/handling, documented standards,
and (via the open design of this document) peer review.

## 1. What this tool does, and does not, establish as fact

Two categories of output exist, and they are never mixed:

- **Facts**: on-chain transfers, account activations, and permission structures, each
  traceable to a specific transaction hash independently verifiable on any public Tron
  explorer or full node. The tracing engine (Sections 2–4 below) produces facts only.
- **Inferences**: controller attribution and address clustering (Section 5). Every inference
  carries a numeric confidence score, the specific signals that produced it, and the
  transaction hashes that are the evidence for each signal. Reports visually and
  structurally separate inferences from facts (see the "INFERENCE, NOT FACT" heading in
  generated HTML reports).

## 2. Tranche accounting: how FIFO/LIFO works on an account-based chain

Tron is account-based, so balances commingle — there is no UTXO to point to. This tool
reconstructs FIFO/LIFO attribution via **tranche accounting**: every inbound transfer to an
address creates a *tranche* (a labeled slice of that address's balance); every outbound
transfer *consumes* tranches, either from the oldest remaining tranche (FIFO) or the newest
(LIFO). A single outbound transaction can draw from multiple tranches (a *split*); each such
draw is recorded as an atomic **consumption event**: `(outbound_tx, tranche_id,
amount_consumed)`. This consumption ledger is the complete, auditable record the rest of
the tool is built on.

**Canonical ordering.** All transfers are ordered by `(block_number, tx_index_in_block,
log_index)`, never by wall-clock timestamp — Tron blocks are ~3 seconds apart and
timestamps collide constantly. `tx_index_in_block` is not returned directly by TronGrid's
convenience endpoints; it is derived by fetching the full block and using the transaction's
position in the block's transaction list (the standard method block explorers use).
`log_index` (needed to disambiguate multiple TRC-20 Transfer events in one transaction) is
derived from each transaction's event log. Both derivations should be spot-checked against
a live TronGrid response before relying on ingestion in production — see the docstring in
`tron_tracer/ingest/trongrid.py`.

**Integer-only arithmetic.** Every amount is stored and computed as an arbitrary-precision
Python integer in the asset's smallest unit (sun for TRX; the token's `decimals` for
TRC-20/TRC-10). Decimal formatting happens only in the report layer, never in tracing logic.

## 3. Policies (every one is a named, recorded parameter)

| Policy | Default | What it means |
|---|---|---|
| `method` | `fifo` | Which end of the tranche queue an outbound draws from first. |
| `fee_policy` | `fee_first` | When one transaction both moves value and burns a TRX fee, which leg drains the TRX tranche book first. Fees are **always TRX-denominated**, even when the transaction moves a different asset (e.g. USDT) — so fee consumption always happens against the sender's TRX book, not the transferred asset's book. `fees_last` is the documented alternative; whichever is used is stated in every report. |
| `dust_threshold` | `0` | Marked amounts below this value terminate a trace branch as `dust` instead of continuing. `0` traces everything. |
| `max_hop_depth` | `25` | Recursion limit for multi-hop tracing. |
| `partial_tranche_marking` | `proportional` | See Section 4. |
| Pre-window balance | synthetic `unknown_origin` tranche, `order_key = -infinity` | If a trace or ingestion window doesn't cover an address's full history, the balance carried in from before the window is modeled as one synthetic tranche that sorts before everything real — so it's always available under FIFO but always consumed last under LIFO relative to in-window tranches with real order keys, and it is visibly labeled `unknown_origin` in every output rather than silently blended in. |
| Self-transfers | tranche identity preserved | An address sending funds to itself does not reset the tranche's position in the queue. The consumed tranche's replacement keeps the **same** `order_key` as the tranche it replaced, not the self-transfer's own position, so an address cannot manipulate FIFO/LIFO ordering by cycling funds through itself. When a replacement tranche ties exactly on `order_key` with another tranche (only possible via this mechanism), FIFO breaks the tie toward the earlier-created tranche and LIFO toward the later-created one — a deterministic, documented tie-break, not a further ordering claim about genuinely simultaneous positions. |
| Same-block ordering | strict | A tranche can only be consumed by a transfer at an equal or later `order_key`; there is no same-block netting shortcut. |
| Rounding | none | Integers only, everywhere. |

## 4. Commingled-tranche attribution across hops (a documented judgment call)

The blueprint this tool was built from describes multi-hop tracing at the level of "follow
consumption of marked tranches to the next address," but leaves one real-world case
underspecified: what happens when a single on-chain transfer at the *next* hop is only
**partially** attributable to the origin being traced, because it was itself funded by a mix
of marked and unmarked tranches at the previous hop.

This tool's answer: each tranche tracks both its full amount and its "marked" (traced)
amount. When a partially-marked tranche is later split across multiple outbound
consumption events, the marked share of each slice is computed by exact integer
floor-division of the marked fraction, with the **final** slice sweeping up whatever
rounding remainder is left — so the marked total across a tranche's entire lifetime is
always exactly conserved, never drifts. This proportional allocation only affects the
human-readable "how much of this hop derives from the origin" figure; the underlying
FIFO/LIFO consumption ledger itself remains exact-integer, chain-accurate, and fully
auditable regardless of marking. Backward tracing uses the same technique in reverse when
scaling a sender's own consumption breakdown down to the fraction actually being traced.

## 5. Attribution signal hierarchy

**Tier 1 — Shared permission keys (confidence 0.98).** Tron's `owner_permission`/
`active_permission` structures list the addresses authorized to sign for an account. If two
different accounts list the same signer address, that is on-chain, cryptographic-grade
evidence of common control. An account whose owner permission is a single key that is *not*
its own address is flagged as directly controlled by that other address.

**Tier 2 — Activation relationship (base confidence 0.55).** `+0.20` if the activator
repeatedly funded the activated account's resources afterward; `+0.10` if activation was via
a deliberate `AccountCreateContract` rather than an incidental first transfer; capped at
**≤0.05** if the activator carries a known service label (exchange, energy-rental service,
gambling site — these activate thousands of unrelated accounts and are the single largest
false-positive source for this signal, so the label whitelist check runs before this signal
is used at all).

**Tier 3 — Behavioral signals (weak alone, combined multiplicatively):**

| Signal | Weight | Concrete detection rule used |
|---|---|---|
| Recurring resource top-ups | 0.35 | ≥3 TRX transfers ≤100 TRX from A to B, each followed by a later B outbound. |
| Full-balance sweeps | 0.30 | ≥2 outbound transfers from B moving ≥95% of B's cumulative available balance at that point. |
| High bidirectional frequency, low overlap | 0.25 | ≥6 transfers total between A and B, and ≤20% Jaccard overlap between their other counterparties. |
| Temporal correlation | 0.15 | Cosine similarity ≥0.8 between 24-bucket hour-of-day activity histograms. **Supporting only — this tool refuses to let it be the sole signal establishing a link.** |
| Shared rare counterparties | 0.15 | Any shared counterparty outside the top 50 most globally common addresses in the case. |
| Sequential activation chains | 0.20 | Consecutive activations (A activates B activates C...) within 100 blocks of each other. |

Every threshold above is a named constant in `tron_tracer/attribution/behavioral.py`, not a
buried magic number — tune per case if needed, but any change should be noted in the case's
own methodology addendum.

**Composite confidence:** `1 − Π(1 − wᵢ)` over present signals, capped at **0.90** for any
link without a Tier 1 signal. When combining tiers for a single address pair, each tier's
*already-resolved* confidence (including any tier-specific cap, like the labeled-activator
cap above) is treated as one signal in this formula — sub-signals are never re-flattened and
recombined from scratch, which would silently defeat tier-specific caps. Every link stores
its full signal list with evidence transaction hashes so the score is fully decomposable.

## 6. Clustering

Union-find over links at or above a per-case confidence threshold (default 0.75). A
cluster's reported strength is the **minimum edge in its maximum-bottleneck spanning tree**
— i.e., the weakest link that is *necessary* to hold the cluster together, computed via
Kruskal's algorithm processing edges in descending confidence order. This is a tighter,
more honest bound than simply reporting the lowest-confidence edge anywhere in the
component. A controller candidate is nominated from any Tier-1 "externally controlled by"
hint touching the cluster, falling back to the member with the most in-cluster edges
(ties broken lexically for determinism). Clusters are always inferences.

## 7. Known limitations (v1)

- **Contract interactions** (DEX swaps, SunSwap, bridges) are trace terminals; decoding
  swap/bridge outputs is out of scope for v1.
- **Cross-chain bridge exits** end the on-Tron trace.
- **Exchange deposit addresses** are terminals; continuing past them requires legal process
  to the exchange. The report identifies the exchange (via labels) to support that request.
- **Label quality**: third-party labels (TronScan) are leads, not evidence, and drift over
  time. Any label load-bearing to a conclusion should be re-verified manually.
- **Historical permission changes**: permissions are captured at a snapshot block; replaying
  `AccountPermissionUpdateContract` history is not implemented in v1. Flag any account with
  permission-update history for manual review.
- **TRX balance reconciliation** can legitimately fail for addresses with staking, voting, or
  resource-delegation activity, since those move balance outside plain transfers. Ingestion
  treats any reconciliation mismatch as a hard error (never a silently-accepted warning) and
  the error message names this as the likely cause so it can be manually reviewed rather than
  mistaken for a data-integrity bug.
- **FIFO vs. LIFO are accounting conventions, not physical facts** about fungible tokens.
  Reports should ideally run both and state whether the conclusion is method-sensitive.

*Admissibility of this tool's output ultimately depends on jurisdiction, the specific case,
and the testifying expert. This document and the golden test suite (`tests/`) are engineering
support for that testimony, not a legal guarantee — have qualified legal/expert counsel
review this methodology before relying on it.*
