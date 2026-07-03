from tron_tracer.attribution.activation import compute_activation_confidence
from tron_tracer.attribution.behavioral import (
    detect_full_balance_sweeps,
    detect_recurring_resource_topups,
    detect_temporal_correlation,
)
from tron_tracer.attribution.clustering import LinkEdge, cluster_links
from tron_tracer.attribution.permissions import (
    build_key_index,
    externally_controlled_by,
    find_shared_key_links,
)
from tron_tracer.attribution.scoring import AttributionSignal, compute_composite_confidence

A = "TAddrA1111111111111111111111111111111"
B = "TAddrB1111111111111111111111111111111"
C = "TAddrC1111111111111111111111111111111"
D = "TAddrD1111111111111111111111111111111"
KEY = "TSharedSignerKey11111111111111111111"


def test_shared_key_index_and_links():
    accounts = {
        A: {"owner_permission": {"keys": [{"address": KEY, "weight": 1}]}, "active_permissions": []},
        B: {"owner_permission": {"keys": [{"address": KEY, "weight": 1}]}, "active_permissions": []},
        C: {"owner_permission": {"keys": [{"address": C, "weight": 1}]}, "active_permissions": []},
    }
    index = build_key_index(accounts)
    assert index[KEY] == {A, B}
    links = find_shared_key_links(index)
    assert len(links) == 1
    assert {links[0].address_a, links[0].address_b} == {A, B}
    assert links[0].confidence == 0.98


def test_externally_controlled_by():
    assert externally_controlled_by(A, {"keys": [{"address": KEY}]}) == KEY
    assert externally_controlled_by(A, {"keys": [{"address": A}]}) is None


def test_activation_confidence_labeled_activator_capped():
    conf, _ = compute_activation_confidence(
        activator_is_labeled_service=True, repeated_resource_funding=True, via_account_create_contract=True,
    )
    assert conf <= 0.05


def test_activation_confidence_deliberate_and_funded():
    conf, signals = compute_activation_confidence(
        activator_is_labeled_service=False, repeated_resource_funding=True, via_account_create_contract=True,
    )
    assert conf == 0.55 + 0.20 + 0.10
    assert len(signals) == 3


def test_recurring_resource_topups_detection(xfer):
    a_to_b = [xfer(f"top{i}", 100 + i, 0, A, B, 1_000_000) for i in range(3)]
    b_outbound = [xfer(f"out{i}", 200 + i, 0, B, C, 500) for i in range(3)]
    result = detect_recurring_resource_topups(a_to_b, b_outbound)
    assert result.present
    assert result.weight == 0.35


def test_full_balance_sweep_detection(xfer):
    b_inbound = [xfer("in1", 100, 0, A, B, 1_000)]
    b_outbound = [xfer("out1", 101, 0, B, C, 990)]  # 99% sweep
    b_inbound2 = [xfer("in2", 102, 0, A, B, 500)]
    b_outbound2 = [xfer("out2", 103, 0, B, C, 495)]
    result = detect_full_balance_sweeps(b_inbound + b_inbound2, b_outbound + b_outbound2)
    assert result.present


def test_temporal_correlation_alone_never_load_bearing():
    hist = [1] * 24
    result = detect_temporal_correlation(hist, hist)
    assert result.present
    signal = AttributionSignal("temporal_correlation", tier=3, weight=result.weight, evidence=[], supporting_only=True)
    confidence, _ = compute_composite_confidence([signal])
    assert confidence == 0.0  # can't establish a link alone


def test_composite_confidence_capped_without_tier1():
    signals = [
        AttributionSignal("recurring_resource_topups", tier=3, weight=0.35, evidence=["tx1"]),
        AttributionSignal("full_balance_sweeps", tier=3, weight=0.30, evidence=["tx2"]),
        AttributionSignal("high_bidirectional_frequency", tier=3, weight=0.25, evidence=["tx3"]),
    ]
    confidence, records = compute_composite_confidence(signals)
    # 1 - (0.65 * 0.70 * 0.75) = 1 - 0.34125 = 0.65875 -> under the 0.90 cap anyway
    assert confidence == round(1 - (0.65 * 0.70 * 0.75), 3)
    assert len(records) == 3


def test_composite_confidence_tier1_uncapped():
    signals = [
        AttributionSignal("shared_key", tier=1, weight=0.98, evidence=["perm"]),
        AttributionSignal("recurring_resource_topups", tier=3, weight=0.35, evidence=["tx1"]),
    ]
    confidence, _ = compute_composite_confidence(signals)
    expected = round(1 - (0.02 * 0.65), 3)
    assert confidence == expected
    assert confidence > 0.90


def test_clustering_union_find_and_bottleneck():
    edges = [
        LinkEdge(A, B, 0.98, "shared_key", []),
        LinkEdge(B, C, 0.80, "behavioral", []),
        LinkEdge(C, D, 0.76, "behavioral", []),
    ]
    clusters = cluster_links(edges, threshold=0.75)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.members == [A, B, C, D]
    # weakest necessary link in the maximum-bottleneck spanning tree is C-D (0.76)
    assert cluster.min_confidence_edge["confidence"] == 0.76


def test_clustering_below_threshold_excluded():
    edges = [LinkEdge(A, B, 0.98, "shared_key", []), LinkEdge(C, D, 0.5, "behavioral", [])]
    clusters = cluster_links(edges, threshold=0.75)
    assert len(clusters) == 1
    assert clusters[0].members == [A, B]


def test_clustering_controller_hint_wins():
    edges = [LinkEdge(A, B, 0.98, "shared_key", [])]
    clusters = cluster_links(edges, threshold=0.75, controller_hints={A: B})
    assert clusters[0].controller_candidate == B
