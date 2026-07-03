"""Wires the permission/activation/behavioral signal detectors and the
scoring/clustering math together against the case database. This is the
`attribute.py --cluster-around <address>` deliverable (blueprint Sec 9
Phase 3).
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from tron_tracer.attribution.activation import compute_activation_confidence
from tron_tracer.attribution.behavioral import (
    detect_full_balance_sweeps,
    detect_high_bidirectional_frequency,
    detect_recurring_resource_topups,
    detect_shared_rare_counterparties,
)
from tron_tracer.attribution.clustering import LinkEdge, cluster_links
from tron_tracer.attribution.permissions import (
    build_key_index,
    externally_controlled_by,
    find_shared_key_links,
)
from tron_tracer.attribution.scoring import AttributionSignal, compute_composite_confidence
from tron_tracer.db.models import Account, AddressLink, Label, Transfer
from tron_tracer.trace.tranche import TransferRecord

SERVICE_CATEGORIES = {"exchange", "energy_rental", "gambling", "bridge", "mixer"}


def _row_to_record(t: Transfer) -> TransferRecord:
    return TransferRecord(
        tx_hash=t.tx_hash, block_number=t.block_number, tx_index=t.tx_index, log_index=t.log_index,
        block_timestamp=t.block_timestamp, from_address=t.from_address, to_address=t.to_address,
        asset_type=t.asset_type, asset_id=t.asset_id, amount=t.amount, fee_sun=t.fee_sun,
        contract_type=t.contract_type,
    )


def _load_labels(session: Session) -> dict[str, set[str]]:
    labeled: dict[str, set[str]] = defaultdict(set)
    for row in session.execute(select(Label)).scalars():
        if row.category in SERVICE_CATEGORIES:
            labeled[row.address].add(row.category)
    return labeled


def _load_accounts(session: Session) -> dict[str, Account]:
    return {a.address: a for a in session.execute(select(Account)).scalars()}


def _load_transfers(session: Session) -> list[Transfer]:
    return list(session.execute(select(Transfer)).scalars())


def build_tier1_links(accounts: dict[str, Account]) -> list[LinkEdge]:
    key_index = build_key_index({
        addr: {"owner_permission": a.owner_permission, "active_permissions": a.active_permissions}
        for addr, a in accounts.items()
    })
    edges = []
    for link in find_shared_key_links(key_index):
        edges.append(LinkEdge(link.address_a, link.address_b, link.confidence, "shared_key",
                               [{"type": "shared_permission_key", "tier": 1, "weight": link.confidence,
                                 "evidence": [link.shared_signer]}], tier=1))
    return edges


def build_tier2_links(accounts: dict[str, Account], transfers: list[Transfer], labeled: dict[str, set[str]]) -> list[LinkEdge]:
    edges = []
    for addr, account in accounts.items():
        activator = account.activated_by
        if not activator:
            continue
        activator_is_service = bool(labeled.get(activator))
        activation_tx = account.activation_tx
        via_create_contract = any(
            t.tx_hash == activation_tx and t.contract_type == "AccountCreateContract" for t in transfers
        )
        funding_count = sum(
            1 for t in transfers if t.from_address == activator and t.to_address == addr and t.asset_id == "TRX"
        )
        confidence, signals = compute_activation_confidence(
            activator_is_labeled_service=activator_is_service,
            repeated_resource_funding=funding_count >= 2,
            via_account_create_contract=via_create_contract,
        )
        for s in signals:
            s["tier"] = 2
        edges.append(LinkEdge(activator, addr, confidence, "activation", signals, tier=2))
    return edges


def _pair_transfers(transfers: list[Transfer], a: str, b: str) -> tuple[list[TransferRecord], list[TransferRecord]]:
    a_to_b = [_row_to_record(t) for t in transfers if t.from_address == a and t.to_address == b]
    b_to_a = [_row_to_record(t) for t in transfers if t.from_address == b and t.to_address == a]
    return a_to_b, b_to_a


def build_tier3_links(transfers: list[Transfer]) -> list[LinkEdge]:
    counterparties: dict[str, set[str]] = defaultdict(set)
    counterparty_freq: dict[str, int] = defaultdict(int)
    pairs: set[tuple[str, str]] = set()
    for t in transfers:
        counterparties[t.from_address].add(t.to_address)
        counterparties[t.to_address].add(t.from_address)
        counterparty_freq[t.to_address] += 1
        counterparty_freq[t.from_address] += 1
        pairs.add(tuple(sorted((t.from_address, t.to_address))))

    global_rank = {addr: rank for rank, (addr, _) in enumerate(
        sorted(counterparty_freq.items(), key=lambda kv: (-kv[1], kv[0]))
    )}

    edges = []
    for a, b in sorted(pairs):
        a_to_b, b_to_a = _pair_transfers(transfers, a, b)
        results = [
            detect_recurring_resource_topups(a_to_b, [_row_to_record(t) for t in transfers if t.from_address == b]),
            detect_recurring_resource_topups(b_to_a, [_row_to_record(t) for t in transfers if t.from_address == a]),
            detect_full_balance_sweeps(
                [_row_to_record(t) for t in transfers if t.to_address == b],
                [_row_to_record(t) for t in transfers if t.from_address == b],
            ),
            detect_high_bidirectional_frequency(
                a_to_b, b_to_a, counterparties[a] - {b}, counterparties[b] - {a},
            ),
            detect_shared_rare_counterparties(counterparties[a] - {b}, counterparties[b] - {a}, global_rank),
        ]
        signals = [
            {"type": r.name, "tier": 3, "weight": r.weight, "evidence": r.evidence}
            for r in results if r.present
        ]
        if not signals:
            continue
        attribution_signals = [
            AttributionSignal(s["type"], 3, s["weight"], s["evidence"]) for s in signals
        ]
        confidence, records = compute_composite_confidence(attribution_signals)
        if confidence <= 0:
            continue
        edges.append(LinkEdge(a, b, confidence, "behavioral", records))
    return edges


def run_attribution(session: Session, threshold: float = 0.75, cluster_around: str | None = None) -> dict:
    accounts = _load_accounts(session)
    transfers = _load_transfers(session)
    labeled = _load_labels(session)

    tier1 = build_tier1_links(accounts)
    tier2 = build_tier2_links(accounts, transfers, labeled)
    tier3 = build_tier3_links(transfers)

    # Merge multi-tier edges touching the same pair into one composite AddressLink.
    by_pair: dict[tuple[str, str], list[LinkEdge]] = defaultdict(list)
    for edge in tier1 + tier2 + tier3:
        key = tuple(sorted((edge.address_a, edge.address_b)))
        by_pair[key].append(edge)

    merged_edges: list[LinkEdge] = []
    for (a, b), pair_edges in sorted(by_pair.items()):
        # Each tier (shared-key, activation, behavioral) has already
        # computed its own fully-resolved confidence for this pair --
        # including tier-specific caps like the labeled-activator cap
        # (activation.py). Re-flattening back to raw sub-signals here
        # would silently lose that cap (a real bug caught in testing:
        # 0.55 base + 0.10 deliberate-activation bonus recombine to 0.595
        # if the cap isn't respected). So the top-level composite treats
        # each tier's confidence as ONE signal; the full sub-signal list
        # is still recorded on the link for evidentiary decomposition.
        tier_signals = [
            AttributionSignal(e.link_type, e.tier, e.confidence, [s.get("type", "") for s in e.signals],
                               supporting_only=False)
            for e in pair_edges
        ]
        confidence, _ = compute_composite_confidence(tier_signals)
        detailed_signals = [sig for e in pair_edges for sig in e.signals]
        link_type = "+".join(sorted({e.link_type for e in pair_edges}))
        merged_edges.append(LinkEdge(a, b, confidence, link_type, detailed_signals,
                                      tier=min(e.tier for e in pair_edges)))

        session.merge(AddressLink(
            address_a=a, address_b=b, link_type=link_type, confidence=confidence,
            signals=detailed_signals, method_version="1.0.0",
        ))
    session.flush()

    controller_hints = {}
    for addr, account in accounts.items():
        controller = externally_controlled_by(addr, account.owner_permission)
        if controller:
            controller_hints[addr] = controller

    clusters = cluster_links(merged_edges, threshold=threshold, controller_hints=controller_hints)

    if cluster_around:
        clusters = [c for c in clusters if cluster_around in c.members]

    return {
        "threshold": threshold,
        "clusters": [
            {
                "members": c.members,
                "min_confidence_edge": c.min_confidence_edge,
                "controller_candidate": c.controller_candidate,
                "edges": [
                    {"address_a": e.address_a, "address_b": e.address_b, "confidence": e.confidence,
                     "link_type": e.link_type, "signals": e.signals}
                    for e in c.edges
                ],
            }
            for c in clusters
        ],
    }
