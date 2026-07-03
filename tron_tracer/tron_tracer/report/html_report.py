"""HTML report generation (blueprint Sec 8). Self-contained HTML -- print
to PDF from any browser for the PDF deliverable; kept as HTML rather
than a PDF-generation dependency per Sec 2's "avoid heavyweight
frameworks" guidance. Sec 5's fact/inference separation is enforced
structurally: the attribution appendix is a visually distinct section
headed "INFERENCE, NOT FACT" and is never merged into the trace
narrative.
"""

from __future__ import annotations

import html
from pathlib import Path

from tron_tracer import METHODOLOGY_VERSION
from tron_tracer.report.format import format_amount
from tron_tracer.report.svg_graph import render_svg

LIMITATIONS_TEXT = """
Known limitations (blueprint Sec 10, restated here per Sec 7 -- always stated up front):
tracing terminates at smart-contract interactions (DEX swaps, bridges) without decoding
swap/bridge outputs; cross-chain bridge exits end the on-Tron trace; exchange deposit
addresses are terminals requiring legal process to the exchange to continue; third-party
labels are leads, not evidence, and drift over time; historical permission changes are
captured only as of the data snapshot, not replayed transaction-by-transaction. FIFO and
LIFO are legal-accounting conventions, not physical facts about fungible tokens -- this
report states which convention was applied.
"""


def _esc(s) -> str:
    return html.escape(str(s))


def render_html_report(
    trace_doc: dict,
    output_path: Path,
    attribution_doc: dict | None = None,
    other_method_doc: dict | None = None,
) -> Path:
    params = trace_doc["parameters"]
    asset_id = params["asset_id"]

    terminal_rows = "".join(
        f"<tr><td>{_esc(t['terminal_type'])}</td><td>{_esc(t['address'] or '')}</td>"
        f"<td>{_esc(format_amount(t['amount'], asset_id))}</td><td>{t['hop']}</td>"
        f"<td>{_esc(t.get('tx_hash') or '')}</td></tr>"
        for t in trace_doc["terminals"]
    )

    hop_sections = []
    for hop in trace_doc["hops"]:
        tranche_source = {t["tranche_id"]: t for t in hop["tranches"]}
        rows = []
        for e in hop["consumptions"]:
            tranche = tranche_source.get(e["tranche_id"], {})
            rows.append(
                f"<tr><td>{_esc(e['outbound_tx'])}</td><td>{_esc(tranche.get('source_tx', ''))}</td>"
                f"<td>{_esc(format_amount(e['amount_consumed'], asset_id))}</td>"
                f"<td>{_esc(format_amount(e['marked_amount_consumed'], asset_id))}</td>"
                f"<td>{_esc(e['to_address'])}</td><td>{_esc(e['kind'])}</td></tr>"
            )
        hop_sections.append(f"""
        <h3>Hop {hop['hop']}: {_esc(hop['address'])}</h3>
        <table class="ledger">
          <thead><tr><th>Outbound tx</th><th>Sourced from tx</th><th>Amount consumed</th>
          <th>Marked (traced) amount</th><th>To</th><th>Kind</th></tr></thead>
          <tbody>{"".join(rows) if rows else '<tr><td colspan="6">No further outbound activity (funds held).</td></tr>'}</tbody>
        </table>""")

    method_sensitivity = ""
    if other_method_doc is not None:
        same = trace_doc["terminal_summary"] == other_method_doc["terminal_summary"]
        method_sensitivity = f"""
        <h2>FIFO vs. LIFO Sensitivity</h2>
        <p>This trace used <b>{_esc(params['policy']['method'].upper())}</b>. Re-running with
        <b>{_esc(other_method_doc['parameters']['policy']['method'].upper())}</b> produced a
        {"<b>method-insensitive</b>" if same else "<b>method-sensitive</b>"} result
        (terminal totals {"match" if same else "differ"} between conventions).</p>
        """

    attribution_section = ""
    if attribution_doc is not None:
        cluster_html = []
        for c in attribution_doc["clusters"]:
            edge_rows = "".join(
                f"<tr><td>{_esc(e['address_a'])}</td><td>{_esc(e['address_b'])}</td>"
                f"<td>{e['confidence']}</td><td>{_esc(e['link_type'])}</td></tr>"
                for e in c["edges"]
            )
            cluster_html.append(f"""
            <div class="cluster">
              <p><b>Members:</b> {", ".join(_esc(m) for m in c['members'])}</p>
              <p><b>Controller candidate (inference):</b> {_esc(c['controller_candidate'] or 'none nominated')}</p>
              <p><b>Weakest necessary link:</b> {c['min_confidence_edge']}</p>
              <table class="ledger"><thead><tr><th>A</th><th>B</th><th>Confidence</th><th>Link type</th></tr></thead>
              <tbody>{edge_rows}</tbody></table>
            </div>""")
        attribution_section = f"""
        <h2 class="inference-heading">ATTRIBUTION APPENDIX -- INFERENCE, NOT FACT</h2>
        <p>Everything below this heading is a probabilistic inference with a documented
        confidence score and signal list, not an established fact. Cluster threshold:
        {attribution_doc['threshold']}.</p>
        {"".join(cluster_html)}
        """

    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Tron Trace Report</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; margin: 2rem; color: #1a202c; }}
h1, h2, h3 {{ color: #1a202c; }}
.inference-heading {{ color: #c53030; border-top: 3px solid #c53030; padding-top: 1rem; }}
table.ledger {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; font-size: 0.85rem; }}
table.ledger th, table.ledger td {{ border: 1px solid #cbd5e0; padding: 4px 8px; text-align: left; }}
table.ledger th {{ background: #edf2f7; }}
.meta {{ background: #f7fafc; padding: 1rem; border-radius: 6px; }}
.limitations {{ background: #fffaf0; border: 1px solid #fbd38d; padding: 1rem; border-radius: 6px; white-space: pre-wrap; font-size: 0.85rem; }}
.cluster {{ border: 1px solid #e2e8f0; padding: 0.75rem; margin-bottom: 1rem; border-radius: 6px; }}
</style></head>
<body>
<h1>Tron Fund Trace Report</h1>
<div class="meta">
  <p><b>Start address:</b> {_esc(params['start_address'])}</p>
  <p><b>Asset:</b> {_esc(asset_id)}</p>
  <p><b>Direction / Method:</b> {_esc(params['direction'])} / {_esc(params['policy']['method'].upper())}</p>
  <p><b>Fee policy:</b> {_esc(params['policy']['fee_policy'])}</p>
  <p><b>Dust threshold:</b> {_esc(params['policy']['dust_threshold'])}</p>
  <p><b>Data snapshot block:</b> {_esc(trace_doc.get('data_snapshot_block'))}</p>
  <p><b>Methodology version:</b> {_esc(trace_doc.get('methodology_version', METHODOLOGY_VERSION))}</p>
  <p><b>Total traced:</b> {_esc(format_amount(trace_doc['total_traced'], asset_id))}</p>
  <p><b>Document SHA-256:</b> <code>{_esc(trace_doc['document_sha256'])}</code></p>
</div>

<h2>Terminal Summary</h2>
<table class="ledger">
  <thead><tr><th>Terminal type</th><th>Address</th><th>Amount</th><th>Hop</th><th>Tx hash</th></tr></thead>
  <tbody>{terminal_rows}</tbody>
</table>

<h2>Trace Graph</h2>
{render_svg(trace_doc)}

<h2>Hop-by-Hop Ledger</h2>
{"".join(hop_sections)}

{method_sensitivity}
{attribution_section}

<h2>Limitations</h2>
<div class="limitations">{_esc(LIMITATIONS_TEXT)}</div>
</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return output_path
