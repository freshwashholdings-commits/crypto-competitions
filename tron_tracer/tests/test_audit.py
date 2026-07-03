import json
import zipfile
from pathlib import Path

from tron_tracer.audit.audit_log import AuditChainBroken, append_entry, verify_chain
from tron_tracer.audit.bundle import build_reproducibility_bundle
from tron_tracer.db.models import AuditLogEntry, RawApiResponse, Transfer
from tron_tracer.db.session import session_scope
from tron_tracer.trace.engine import InMemoryProvider, run_forward_trace
from tron_tracer.trace.policies import TracePolicy

A = "TAddrA1111111111111111111111111111111"
X = "TAddrX1111111111111111111111111111111"


def test_audit_chain_append_and_verify(tmp_path):
    db_url = f"sqlite:///{tmp_path}/audit.db"
    with session_scope(db_url) as session:
        append_entry(session, "ingest_start", {"address": A})
        append_entry(session, "trace_run", {"address": A, "method": "fifo"})
        verify_chain(session)  # should not raise


def test_audit_chain_detects_tampering(tmp_path):
    db_url = f"sqlite:///{tmp_path}/audit2.db"
    with session_scope(db_url) as session:
        append_entry(session, "ingest_start", {"address": A})
        append_entry(session, "trace_run", {"address": A})

    with session_scope(db_url) as session:
        entry = session.get(AuditLogEntry, 1)
        entry.payload = {"address": "TAMPERED"}
        session.flush()

    with session_scope(db_url) as session:
        try:
            verify_chain(session)
            assert False, "expected AuditChainBroken"
        except AuditChainBroken:
            pass


def test_determinism_full_trace_rerun_identical_hash():
    from tests.conftest import make_transfer as xfer

    transfers = [
        xfer("tx1", 100, 0, A, X, 1_000),
        xfer("tx2", 101, 0, X, "TExchange1111111111111111111111111111", 900),
    ]
    provider = InMemoryProvider(transfers, labeled={"TExchange1111111111111111111111111111"})
    doc1 = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])
    doc2 = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])
    assert doc1 == doc2
    assert doc1["document_sha256"] == doc2["document_sha256"]


def test_reproducibility_bundle_contains_raw_responses(tmp_path):
    db_url = f"sqlite:///{tmp_path}/case.db"
    with session_scope(db_url) as session:
        raw = RawApiResponse(source="trongrid", endpoint="/v1/accounts/X/transactions", params={},
                              http_status=200, body='{"data": []}', sha256="abc123")
        session.add(raw)
        session.flush()
        session.add(Transfer(
            tx_hash="tx1", block_number=100, tx_index=0, log_index=0, block_timestamp=0,
            from_address=A, to_address=X, asset_type="TRX", asset_id="TRX", amount=1_000,
            raw_response_id=raw.id,
        ))
        session.flush()

        from tests.conftest import make_transfer as xfer
        transfers = [xfer("tx1", 100, 0, A, X, 1_000)]
        provider = InMemoryProvider(transfers)
        doc = run_forward_trace(X, "TRX", provider, TracePolicy(method="fifo"), seed_tx_hashes=["tx1"])

        bundle_path = build_reproducibility_bundle(session, doc, tmp_path / "bundle.zip")

    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as zf:
        names = zf.namelist()
        assert "trace.json" in names
        assert "manifest.json" in names
        assert any(n.startswith("raw_responses/") for n in names)
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["raw_response_count"] == 1
        assert manifest["trace_document_sha256"] == doc["document_sha256"]
