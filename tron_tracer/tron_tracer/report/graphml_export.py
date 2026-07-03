"""Trace graph visual data (blueprint Sec 8.3/8.5): DAG with edge widths
proportional to amount, terminals distinguished by node attribute.
Exported as GraphML for import into i2/Maltego-style tools."""

from __future__ import annotations

from pathlib import Path

import networkx as nx


def build_trace_graph(trace_doc: dict) -> nx.DiGraph:
    g = nx.DiGraph()
    start_address = trace_doc["parameters"]["start_address"]
    g.add_node(start_address, node_type="origin", hop=0)

    for hop in trace_doc.get("hops", []):
        address = hop["address"]
        g.add_node(address, node_type=g.nodes.get(address, {}).get("node_type", "hop"), hop=hop["hop"])
        for e in hop.get("consumptions", []):
            if e["kind"] in ("self_transfer", "fee_burn"):
                continue
            dest = e["to_address"]
            g.add_node(dest, node_type=g.nodes.get(dest, {}).get("node_type", "hop"))
            if g.has_edge(address, dest):
                g[address][dest]["amount"] += e["amount_consumed"]
                g[address][dest]["marked_amount"] += e["marked_amount_consumed"]
            else:
                g.add_edge(address, dest, amount=e["amount_consumed"], marked_amount=e["marked_amount_consumed"],
                            tx_hash=e["outbound_tx"])

    for t in trace_doc.get("terminals", []):
        if t["address"]:
            g.add_node(t["address"], node_type=t["terminal_type"])

    return g


def write_graphml(trace_doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    g = build_trace_graph(trace_doc)
    nx.write_graphml(g, path)
    return path
