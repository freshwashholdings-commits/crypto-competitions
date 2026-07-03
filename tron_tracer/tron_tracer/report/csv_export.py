"""Flat consumption ledger CSV -- for spreadsheet review (blueprint Sec 8.5)."""

from __future__ import annotations

import csv
from pathlib import Path


def write_consumption_ledger_csv(trace_doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "hop", "address", "outbound_tx", "outbound_order_key", "tranche_id", "tranche_source_tx",
            "amount_consumed", "marked_amount_consumed", "to_address", "kind",
        ])
        for hop in trace_doc.get("hops", []):
            tranche_source = {t["tranche_id"]: t["source_tx"] for t in hop.get("tranches", [])}
            for e in hop.get("consumptions", []):
                writer.writerow([
                    hop["hop"], hop["address"], e["outbound_tx"], "|".join(map(str, e["outbound_order_key"])),
                    e["tranche_id"], tranche_source.get(e["tranche_id"], ""),
                    e["amount_consumed"], e["marked_amount_consumed"], e["to_address"], e["kind"],
                ])
    return path
