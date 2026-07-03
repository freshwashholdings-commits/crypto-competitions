"""Unified CLI: `tron-tracer ingest|trace|attribute|report ...`
(blueprint Sec 9 phase deliverables, combined into one entry point)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from tron_tracer.attribution.orchestrate import run_attribution
from tron_tracer.audit.audit_log import append_entry, verify_chain
from tron_tracer.audit.bundle import build_reproducibility_bundle
from tron_tracer.config import DEFAULT_DB_URL, ClientConfig
from tron_tracer.db.session import session_scope
from tron_tracer.ingest.backfill import ReconciliationError, backfill_address
from tron_tracer.report.csv_export import write_consumption_ledger_csv
from tron_tracer.report.graphml_export import write_graphml
from tron_tracer.report.html_report import render_html_report
from tron_tracer.trace.canonical import canonical_json_dumps
from tron_tracer.trace.db_provider import DbTransferProvider
from tron_tracer.trace.engine import run_backward_trace, run_forward_trace
from tron_tracer.trace.policies import TracePolicy


@click.group()
def cli():
    """Tron Address Tracer & Analyzer."""


# -- ingest --------------------------------------------------------------

@cli.group()
def ingest():
    """Backfill transfers/accounts from TronGrid into the case database."""


@ingest.command("backfill")
@click.argument("address")
@click.option("--asset", default="USDT", help="'TRX', 'USDT', or a TRC-20 contract address")
@click.option("--db-url", default=DEFAULT_DB_URL)
@click.option("--skip-reconciliation", is_flag=True, default=False)
def ingest_backfill(address: str, asset: str, db_url: str, skip_reconciliation: bool):
    with session_scope(db_url) as session:
        try:
            result = backfill_address(session, address, asset, ClientConfig(), reconcile=not skip_reconciliation)
        except ReconciliationError as exc:
            raise click.ClickException(str(exc))
        click.echo(json.dumps(asdict(result), indent=2))


# -- trace -----------------------------------------------------------------

@cli.group()
def trace():
    """Run a deterministic FIFO/LIFO trace against the case database."""


@trace.command("run")
@click.option("--address", required=True)
@click.option("--asset", required=True)
@click.option("--method", type=click.Choice(["fifo", "lifo"]), default="fifo")
@click.option("--direction", type=click.Choice(["forward", "backward"]), default="forward")
@click.option("--seed-tx", multiple=True, help="Forward: one or more inbound tx hashes to trace. "
                                                 "Backward: a single outbound tx hash (omit for current holding).")
@click.option("--dust-threshold", default=0, type=int)
@click.option("--fee-policy", type=click.Choice(["fee_first", "fees_last"]), default="fee_first")
@click.option("--max-hop-depth", default=25, type=int)
@click.option("--db-url", default=DEFAULT_DB_URL)
@click.option("--output", required=True, type=click.Path())
def trace_run(address, asset, method, direction, seed_tx, dust_threshold, fee_policy, max_hop_depth, db_url, output):
    policy = TracePolicy(method=method, fee_policy=fee_policy, dust_threshold=dust_threshold,
                          max_hop_depth=max_hop_depth)
    with session_scope(db_url) as session:
        provider = DbTransferProvider(session)
        if direction == "forward":
            doc = run_forward_trace(address, asset, provider, policy, seed_tx_hashes=list(seed_tx) or None)
        else:
            doc = run_backward_trace(address, asset, provider, policy,
                                      seed_outbound_tx=seed_tx[0] if seed_tx else None)
        append_entry(session, "trace_run", {
            "parameters": doc["parameters"], "document_sha256": doc["document_sha256"],
        })
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(canonical_json_dumps(doc))
    click.echo(f"wrote {output} (document_sha256={doc['document_sha256']})")


# -- attribute ---------------------------------------------------------------

@cli.group()
def attribute():
    """Run the attribution engine (permissions, activation, behavioral signals, clustering)."""


@attribute.command("run")
@click.option("--cluster-around", default=None)
@click.option("--threshold", default=0.75, type=float)
@click.option("--db-url", default=DEFAULT_DB_URL)
@click.option("--output", required=True, type=click.Path())
def attribute_run(cluster_around, threshold, db_url, output):
    with session_scope(db_url) as session:
        result = run_attribution(session, threshold=threshold, cluster_around=cluster_around)
        append_entry(session, "attribution_run", {"threshold": threshold, "cluster_around": cluster_around})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(canonical_json_dumps(result))
    click.echo(f"wrote {output} ({len(result['clusters'])} cluster(s) at threshold {threshold})")


# -- report ------------------------------------------------------------------

@cli.group()
def report():
    """Render exports (HTML/CSV/GraphML/reproducibility bundle) from a trace JSON."""


@report.command("generate")
@click.option("--trace-file", "trace_path", required=True, type=click.Path(exists=True))
@click.option("--attribution-file", "attribution_path", default=None, type=click.Path(exists=True))
@click.option("--out-dir", required=True, type=click.Path())
@click.option("--db-url", default=None, help="Required only for --bundle (needs raw response archive).")
@click.option("--bundle", is_flag=True, default=False)
def report_generate(trace_path, attribution_path, out_dir, db_url, bundle):
    doc = json.loads(Path(trace_path).read_text())
    attribution_doc = json.loads(Path(attribution_path).read_text()) if attribution_path else None
    out = Path(out_dir)
    render_html_report(doc, out / "report.html", attribution_doc=attribution_doc)
    write_consumption_ledger_csv(doc, out / "ledger.csv")
    write_graphml(doc, out / "graph.graphml")
    (out / "trace.json").write_text(canonical_json_dumps(doc))
    if bundle:
        if not db_url:
            raise click.ClickException("--bundle requires --db-url")
        with session_scope(db_url) as session:
            build_reproducibility_bundle(session, doc, out / "bundle.zip")
    click.echo(f"wrote report to {out}")


# -- audit ---------------------------------------------------------------

@cli.group()
def audit():
    """Inspect and verify the case's hash-chained audit log."""


@audit.command("verify")
@click.option("--db-url", default=DEFAULT_DB_URL)
def audit_verify(db_url):
    with session_scope(db_url) as session:
        verify_chain(session)
    click.echo("audit chain OK")


if __name__ == "__main__":
    cli()
