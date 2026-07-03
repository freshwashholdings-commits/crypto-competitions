#!/usr/bin/env bash
# Double-click launcher for the Tron Address Tracer & Analyzer.
# Handles first-run setup, prompts for a case, runs ingest -> trace ->
# attribute -> report, and opens the resulting report.html automatically.
# See README.md for what each step does; this script is just a
# convenience wrapper around the same `tron-tracer` CLI commands.

cd "$(dirname "$0")" || exit 1

echo "=== Tron Address Tracer & Analyzer ==="
echo

if [ ! -d ".venv" ]; then
  echo "First run: setting up Python environment (this happens once)..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -e ".[dev]"
  echo "Setup complete."
  echo
fi

PY="./.venv/bin/python"
CLI="$PY -m tron_tracer.cli"

CONFIG_FILE=".tron_tracer_config"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

if [ -z "$TRONGRID_API_KEY" ]; then
  echo "No TronGrid API key saved yet. Get a free one at https://www.trongrid.io"
  read -r -p "TronGrid API key: " TRONGRID_API_KEY
  echo "TRONGRID_API_KEY=$TRONGRID_API_KEY" > "$CONFIG_FILE"
fi
export TRONGRID_API_KEY

read -r -p "Tron address to trace: " ADDRESS
if [ -z "$ADDRESS" ]; then
  echo "No address entered, exiting."
  read -r -p "Press Enter to close..." _
  exit 1
fi

read -r -p "Asset (TRX / USDT / a TRC-20 contract address) [USDT]: " ASSET
ASSET=${ASSET:-USDT}
read -r -p "Method (fifo/lifo) [fifo]: " METHOD
METHOD=${METHOD:-fifo}
read -r -p "Direction (forward/backward) [forward]: " DIRECTION
DIRECTION=${DIRECTION:-forward}
read -r -p "Specific inbound tx hash to trace (leave blank to trace everything currently held): " SEED_TX

SAFE_ADDR=$(echo "$ADDRESS" | tr -cd '[:alnum:]')
CASE_DB="sqlite:///case_${SAFE_ADDR}.db"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="out/${STAMP}"
mkdir -p "$OUT_DIR"

echo
echo "--- Ingesting $ADDRESS ($ASSET) ---"
$CLI ingest backfill "$ADDRESS" --asset "$ASSET" --db-url "$CASE_DB"
if [ $? -ne 0 ]; then
  echo "!! Ingestion failed -- see the error above."
  echo "!! (A balance-reconciliation failure is expected for addresses with"
  echo "!!  staking/voting activity; see METHODOLOGY.md Section 7.)"
  read -r -p "Press Enter to close..." _
  exit 1
fi

echo
echo "--- Tracing ($METHOD, $DIRECTION) ---"
TRACE_ARGS=(--address "$ADDRESS" --asset "$ASSET" --method "$METHOD" --direction "$DIRECTION" \
  --db-url "$CASE_DB" --output "$OUT_DIR/trace.json")
if [ -n "$SEED_TX" ]; then
  TRACE_ARGS+=(--seed-tx "$SEED_TX")
fi
$CLI trace run "${TRACE_ARGS[@]}"
if [ $? -ne 0 ]; then
  echo "!! Trace failed -- see the error above."
  read -r -p "Press Enter to close..." _
  exit 1
fi

echo
echo "--- Attributing ---"
$CLI attribute run --cluster-around "$ADDRESS" --db-url "$CASE_DB" --output "$OUT_DIR/attribution.json"

echo
echo "--- Building report ---"
$CLI report generate --trace-file "$OUT_DIR/trace.json" --attribution-file "$OUT_DIR/attribution.json" \
  --out-dir "$OUT_DIR/report"

REPORT="$OUT_DIR/report/report.html"
echo
echo "Report ready: $REPORT"

if command -v open >/dev/null 2>&1; then
  open "$REPORT"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$REPORT"
else
  echo "Open this file manually in your browser: $REPORT"
fi

read -r -p "Press Enter to close..." _
