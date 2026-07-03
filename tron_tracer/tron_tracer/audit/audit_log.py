"""Hash-chained, append-only audit log (blueprint Sec 4, Sec 7).

Every ingestion run, trace run, attribution run, and export is recorded
here. Each entry's hash covers the previous entry's hash, so altering or
deleting any historical entry is detectable by recomputing the chain.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from tron_tracer.db.models import AuditLogEntry
from tron_tracer.trace.canonical import canonical_json_dumps

GENESIS_HASH = "0" * 64


def _compute_hash(prev_hash: str, event_type: str, payload: dict) -> str:
    material = prev_hash + "|" + event_type + "|" + canonical_json_dumps(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_entry(session: Session, event_type: str, payload: dict) -> AuditLogEntry:
    last = session.execute(
        select(AuditLogEntry).order_by(AuditLogEntry.seq.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last.this_hash if last else GENESIS_HASH
    this_hash = _compute_hash(prev_hash, event_type, payload)
    entry = AuditLogEntry(event_type=event_type, payload=payload, prev_hash=prev_hash, this_hash=this_hash)
    session.add(entry)
    session.flush()
    return entry


class AuditChainBroken(Exception):
    pass


def verify_chain(session: Session) -> None:
    """Recompute every hash in sequence order; raise on the first mismatch."""
    entries = session.execute(select(AuditLogEntry).order_by(AuditLogEntry.seq.asc())).scalars().all()
    prev_hash = GENESIS_HASH
    for entry in entries:
        if entry.prev_hash != prev_hash:
            raise AuditChainBroken(f"seq={entry.seq}: prev_hash mismatch")
        expected = _compute_hash(prev_hash, entry.event_type, entry.payload)
        if entry.this_hash != expected:
            raise AuditChainBroken(f"seq={entry.seq}: this_hash mismatch (tampered payload?)")
        prev_hash = entry.this_hash
