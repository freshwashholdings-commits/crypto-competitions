# Tron Address Tracer & Analyzer

A forensic tracing tool for the Tron blockchain: deterministic FIFO/LIFO fund tracing,
controller attribution (shared permission keys, activation relationships, behavioral
signals), and confidence-scored address clustering. Built to the design in
[`METHODOLOGY.md`](METHODOLOGY.md) — read that first for *why* things work this way; this
file is just the "how to run it."

Every fact used in a trace is traceable to an on-chain transaction hash. Every inference
(attribution, clustering) carries a numeric confidence score, its supporting signals, and
evidence transaction hashes, and is never presented as fact.

## Install

```bash
cd tron_tracer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Set a TronGrid API key before ingesting real data:

```bash
export TRONGRID_API_KEY=your_key_here
```

## Pipeline

```
ingest  -->  trace  -->  attribute  -->  report
(TronGrid)   (FIFO/LIFO)  (clustering)   (HTML/CSV/GraphML/bundle)
```

Every command shares one case database (SQLite by default: `tron_tracer_case.db`;
point `--db-url` / `TRON_TRACER_DB_URL` at a Postgres URL for a larger case).

### 1. Ingest

```bash
tron-tracer ingest backfill <address> --asset USDT
tron-tracer ingest backfill <address> --asset TRX
tron-tracer ingest backfill <address> --asset <trc20-contract-address>
```

Pulls the address's transaction/transfer history from TronGrid, archives every raw API
response (hashed, for the evidentiary chain), normalizes it into the `transfers`/`accounts`
tables, and **hard-fails** if the computed balance doesn't reconcile against the
node-reported balance — see METHODOLOGY.md Section 7 for when that's expected (e.g. staking
activity) rather than a bug.

### 2. Trace

```bash
tron-tracer trace run \
  --address <address> --asset USDT --method fifo --direction forward \
  --seed-tx <deposit_tx_hash> --output out/trace.json
```

`--direction backward` traces a specific outbound tx (`--seed-tx <hash>`) or the address's
current holdings (omit `--seed-tx`) back to their funding origin. `--method lifo` switches
convention. Output is canonical, deterministic JSON — the same parameters against the same
data always produce byte-identical output (see `document_sha256` in the output).

### 3. Attribute

```bash
tron-tracer attribute run --cluster-around <address> --threshold 0.75 --output out/attribution.json
```

Runs the full signal hierarchy (permissions, activation, behavioral) against every address
currently in the case database and returns the cluster(s) containing `--cluster-around`
(omit it to get every cluster in the case).

### 4. Report

```bash
tron-tracer report generate \
  --trace-file out/trace.json --attribution-file out/attribution.json \
  --out-dir out/report --bundle --db-url sqlite:///tron_tracer_case.db
```

Writes `report.html` (executive summary, hop-by-hop ledger, inline SVG trace graph,
attribution appendix clearly headed as inference, limitations), `ledger.csv` (flat
consumption ledger), `graph.graphml` (for i2/Maltego/Gephi), and — with `--bundle` — a
`bundle.zip` reproducibility package (parameters, methodology version, code version, trace
JSON + hash, every raw API response relied upon) suitable for handing to opposing counsel's
expert.

### Audit log

```bash
tron-tracer audit verify --db-url sqlite:///tron_tracer_case.db
```

Recomputes the hash chain over every ingestion/trace/attribution event and fails loudly if
anything was tampered with after the fact.

## Development

```bash
pip install -e ".[dev]"
pytest            # golden tests + integration tests, ~35 cases across every phase
```

The tranche-accounting golden tests in `tests/test_tranche_engine.py` are hand-computed —
each expected number is worked out in the test's own comments, so they double as exhibits
for explaining the methodology to a non-engineer.

## Layout

```
tron_tracer/
  config.py                  asset constants, client config
  db/                         SQLAlchemy schema (transfers, accounts, labels,
                               address_links, audit_log, raw_api_responses)
  ingest/                     TronGrid/TronScan clients, rate limiting, archiving,
                               address encoding, backfill orchestration
  trace/                      tranche accounting engine, multi-hop trace engine,
                               policies, canonical JSON, DB-backed transfer provider
  attribution/                permission keys, activation scoring, behavioral
                               signals, composite scoring, union-find clustering
  audit/                      hash-chained audit log, reproducibility bundle export
  report/                     HTML/CSV/GraphML export, inline SVG trace graph
  cli.py                      `tron-tracer` entry point
tests/                        golden + integration tests for every phase
METHODOLOGY.md                the "why," written for a non-engineer reader
```
