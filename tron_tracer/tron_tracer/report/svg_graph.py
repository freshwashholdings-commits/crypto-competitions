"""Minimal, dependency-free SVG rendering of the trace DAG (blueprint Sec
8.3): nodes laid out in columns by hop, edge stroke width proportional to
amount, terminal nodes color-coded by terminal type. Deliberately simple
(no layout library) -- GraphML export (graphml_export.py) is the path
for full-featured visual tools (i2/Maltego/Gephi); this SVG is for quick
inline viewing in the HTML report."""

from __future__ import annotations

import html
import math

from tron_tracer.report.graphml_export import build_trace_graph

TERMINAL_COLORS = {
    "origin": "#2b6cb0",
    "hop": "#4a5568",
    "service": "#38a169",
    "contract_interaction": "#805ad5",
    "dust": "#a0aec0",
    "holding": "#d69e2e",
    "max_hop_depth": "#e53e3e",
    "fee_burn": "#718096",
    "pre_window_unknown": "#718096",
}

COL_WIDTH = 220
ROW_HEIGHT = 70
NODE_RADIUS = 8
MARGIN = 60


def render_svg(trace_doc: dict) -> str:
    g = build_trace_graph(trace_doc)

    by_hop: dict[int, list[str]] = {}
    for node, data in g.nodes(data=True):
        hop = data.get("hop", 0)
        by_hop.setdefault(hop, []).append(node)
    for hop in by_hop:
        by_hop[hop].sort()

    positions: dict[str, tuple[int, int]] = {}
    for hop, nodes in sorted(by_hop.items()):
        for i, node in enumerate(nodes):
            positions[node] = (MARGIN + hop * COL_WIDTH, MARGIN + i * ROW_HEIGHT)

    max_x = max((x for x, _ in positions.values()), default=0) + COL_WIDTH
    max_y = max((y for _, y in positions.values()), default=0) + ROW_HEIGHT

    max_amount = max((d["amount"] for _, _, d in g.edges(data=True)), default=1)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{max_x}" height="{max_y}" '
             f'viewBox="0 0 {max_x} {max_y}" font-family="monospace" font-size="11">']
    parts.append(f'<rect width="{max_x}" height="{max_y}" fill="white"/>')

    for a, b, data in g.edges(data=True):
        if a not in positions or b not in positions:
            continue
        x1, y1 = positions[a]
        x2, y2 = positions[b]
        width = 1 + 6 * (math.log(data["amount"] + 1) / math.log(max_amount + 1))
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#666" stroke-width="{width:.2f}" opacity="0.6"/>'
        )

    for node, (x, y) in positions.items():
        node_type = g.nodes[node].get("node_type", "hop")
        color = TERMINAL_COLORS.get(node_type, "#4a5568")
        label = html.escape(node[:10] + "..." + node[-4:] if len(node) > 18 else node)
        parts.append(f'<circle cx="{x}" cy="{y}" r="{NODE_RADIUS}" fill="{color}"/>')
        parts.append(f'<text x="{x + NODE_RADIUS + 4}" y="{y + 4}">{label}</text>')

    parts.append("</svg>")
    return "\n".join(parts)
