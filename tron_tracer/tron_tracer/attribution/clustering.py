"""Union-find clustering over confidence-scored links (blueprint Sec 6.2).

A cluster is only as strong as its weakest *necessary* connection: we
compute the maximum-bottleneck spanning tree of each connected component
(process edges in descending confidence via Kruskal's algorithm) so the
reported "minimum confidence edge" is the tightest honest bound on the
whole cluster, not just the lowest edge that happens to exist somewhere
in it. Clusters are inferences, never fact (Sec 6.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CLUSTER_THRESHOLD = 0.75


@dataclass
class LinkEdge:
    address_a: str
    address_b: str
    confidence: float
    link_type: str
    signals: list[dict]
    tier: int = 3


@dataclass
class Cluster:
    members: list[str]
    min_confidence_edge: dict | None
    controller_candidate: str | None
    edges: list[LinkEdge]


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}
        self.bottleneck: dict[str, float] = {}  # keyed by root
        self.bottleneck_edge: dict[str, LinkEdge | None] = {}

    def make(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self.bottleneck[x] = float("inf")
            self.bottleneck_edge[x] = None

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, edge: LinkEdge) -> None:
        self.make(edge.address_a)
        self.make(edge.address_b)
        ra, rb = self.find(edge.address_a), self.find(edge.address_b)
        if ra == rb:
            # already connected; edge doesn't lower the tree's bottleneck
            # (it's not part of the maximum-bottleneck spanning tree)
            return
        new_bottleneck = min(self.bottleneck[ra], self.bottleneck[rb], edge.confidence)
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        self.bottleneck[ra] = new_bottleneck
        self.bottleneck_edge[ra] = edge


def cluster_links(
    edges: list[LinkEdge],
    threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    controller_hints: dict[str, str] | None = None,
) -> list[Cluster]:
    controller_hints = controller_hints or {}
    qualifying = [e for e in edges if e.confidence >= threshold]

    uf = _UnionFind()
    for e in qualifying:
        uf.make(e.address_a)
        uf.make(e.address_b)
    for e in sorted(qualifying, key=lambda e: -e.confidence):
        uf.union(e)

    members_by_root: dict[str, list[str]] = {}
    edges_by_root: dict[str, list[LinkEdge]] = {}
    for addr in uf.parent:
        root = uf.find(addr)
        members_by_root.setdefault(root, []).append(addr)
    for e in qualifying:
        root = uf.find(e.address_a)
        edges_by_root.setdefault(root, []).append(e)

    clusters = []
    for root, members in members_by_root.items():
        if len(members) < 2:
            continue
        cluster_edges = edges_by_root.get(root, [])
        bottleneck_edge = uf.bottleneck_edge.get(root)
        min_edge_dict = None
        if bottleneck_edge:
            min_edge_dict = {
                "address_a": bottleneck_edge.address_a, "address_b": bottleneck_edge.address_b,
                "confidence": bottleneck_edge.confidence, "link_type": bottleneck_edge.link_type,
            }
        controller = _nominate_controller(members, controller_hints, cluster_edges)
        clusters.append(Cluster(
            members=sorted(members), min_confidence_edge=min_edge_dict,
            controller_candidate=controller, edges=cluster_edges,
        ))
    return sorted(clusters, key=lambda c: c.members)


def _nominate_controller(members: list[str], controller_hints: dict[str, str], edges: list[LinkEdge]) -> str | None:
    # 1) A Tier-1 externally-controlled-by hint pointing at a member wins outright.
    hinted = {controller_hints[m] for m in members if m in controller_hints}
    if len(hinted) == 1:
        return next(iter(hinted))
    # 2) Otherwise the member with the most edges within the cluster (highest
    #    connectivity -- a common proxy for "hub" identity) is nominated,
    #    ties broken lexically for determinism.
    degree: dict[str, int] = {m: 0 for m in members}
    for e in edges:
        degree[e.address_a] = degree.get(e.address_a, 0) + 1
        degree[e.address_b] = degree.get(e.address_b, 0) + 1
    if not degree:
        return None
    max_degree = max(degree.values())
    if max_degree == 0:
        return None
    candidates = sorted(a for a, d in degree.items() if d == max_degree)
    return candidates[0]
