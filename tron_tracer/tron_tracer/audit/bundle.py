"""Reproducibility bundle export (blueprint Sec 7): parameters, methodology
version, code version (git commit), trace output JSON + hash, and the
raw-response ids relied upon -- the package handed to opposing counsel's
expert so every fact can be reproduced from an independent node/explorer.
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tron_tracer import METHODOLOGY_VERSION
from tron_tracer.db.models import RawApiResponse, Transfer
from tron_tracer.trace.canonical import canonical_json_dumps, canonical_sha256


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _tx_hashes_in_trace(trace_doc: dict) -> set[str]:
    hashes: set[str] = set()
    for hop in trace_doc.get("hops", []):
        for tranche in hop.get("tranches", []):
            if tranche.get("source_tx") not in (None, "unknown_origin"):
                hashes.add(tranche["source_tx"])
            hashes.update(tranche.get("pass_through_txs") or [])
        for consumption in hop.get("consumptions", []):
            if consumption.get("outbound_tx"):
                hashes.add(consumption["outbound_tx"])
    for terminal in trace_doc.get("terminals", []):
        if terminal.get("tx_hash"):
            hashes.add(terminal["tx_hash"])
    return hashes


def collect_raw_response_ids(session: Session, trace_doc: dict) -> list[int]:
    tx_hashes = _tx_hashes_in_trace(trace_doc)
    if not tx_hashes:
        return []
    ids = session.execute(
        select(Transfer.raw_response_id).where(Transfer.tx_hash.in_(tx_hashes), Transfer.raw_response_id.isnot(None))
    ).scalars().all()
    return sorted(set(ids))


def build_reproducibility_bundle(session: Session, trace_doc: dict, output_path: Path) -> Path:
    raw_ids = collect_raw_response_ids(session, trace_doc)
    raw_rows = session.execute(select(RawApiResponse).where(RawApiResponse.id.in_(raw_ids))).scalars().all() if raw_ids else []

    manifest = {
        "methodology_version": METHODOLOGY_VERSION,
        "code_version_git_commit": _git_commit(),
        "trace_document_sha256": trace_doc.get("document_sha256"),
        "trace_parameters": trace_doc.get("parameters"),
        "raw_response_ids_relied_upon": raw_ids,
        "raw_response_count": len(raw_rows),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.json", canonical_json_dumps(trace_doc))
        zf.writestr("manifest.json", canonical_json_dumps(manifest))
        for row in raw_rows:
            zf.writestr(
                f"raw_responses/{row.id}_{row.source}_{row.sha256[:12]}.json",
                json.dumps({
                    "source": row.source, "endpoint": row.endpoint, "params": row.params,
                    "http_status": row.http_status, "sha256": row.sha256,
                    "retrieved_at": row.retrieved_at.isoformat(), "body": row.body,
                }, indent=2, sort_keys=True),
            )
    return output_path
