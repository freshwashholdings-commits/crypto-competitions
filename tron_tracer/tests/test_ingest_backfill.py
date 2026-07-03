"""Integration test for the ingestion pipeline (blueprint Sec 9 Phase 1
deliverable) using a mocked HTTP transport instead of live TronGrid --
keeps ingestion deterministic and testable per Sec 3.4's own
archive-then-parse design, and avoids depending on network access or an
API key in CI.
"""

import httpx
import pytest

from tron_tracer.config import ClientConfig
from tron_tracer.db.models import RawApiResponse, Transfer
from tron_tracer.db.session import session_scope
from tron_tracer.ingest.backfill import ReconciliationError, backfill_address

# Hex-encoded 41-prefixed Tron addresses (protobuf-native form used in raw_data.contract)
# and their real base58check encodings (must match exactly -- normalize_address() converts
# hex -> base58 during ingestion, so the mocked endpoint path and the expected stored
# to_address both have to be the genuine encoding, not an arbitrary placeholder string).
ADDRESS_HEX = "410000000000000000000000000000000000000001"
SENDER_HEX = "410000000000000000000000000000000000000002"
ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKLxmGkn"


def _make_handler(node_balance: int):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1/accounts/{ADDRESS}":
            return httpx.Response(200, json={
                "data": [{"balance": node_balance, "owner_permission": None, "active_permission": []}]
            })
        if path == f"/v1/accounts/{ADDRESS}/transactions":
            return httpx.Response(200, json={
                "data": [{
                    "txID": "tx1",
                    "blockNumber": 100,
                    "block_timestamp": 1000,
                    "ret": [{"contractRet": "SUCCESS", "fee": 0}],
                    "raw_data": {"contract": [{
                        "type": "TransferContract",
                        "parameter": {"value": {
                            "owner_address": SENDER_HEX, "to_address": ADDRESS_HEX, "amount": 100,
                        }},
                    }]},
                }],
                "meta": {},  # no fingerprint/next -> exhausted after one page
            })
        if path == "/wallet/getblockbynum":
            return httpx.Response(200, json={"transactions": [{"txID": "tx1"}]})
        if path == f"/v1/accounts/{ADDRESS}/transactions/trc20":
            return httpx.Response(200, json={"data": [], "meta": {}})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def test_backfill_ingests_reconciles_and_archives(tmp_path):
    transport = httpx.MockTransport(_make_handler(node_balance=100))
    db_url = f"sqlite:///{tmp_path}/case.db"

    with session_scope(db_url) as session:
        result = backfill_address(
            session, ADDRESS, "TRX", ClientConfig(trongrid_api_key="test"), transport=transport,
        )
        assert result.native_rows_ingested == 1
        assert result.reconciled is True
        assert result.computed_balance == 100
        assert result.node_balance == 100

        stored = session.query(Transfer).one()
        assert stored.amount == 100
        assert isinstance(stored.amount, int)  # SunInt round-trips as a real int, not str/float
        assert stored.from_address.startswith("T")  # hex -> base58 conversion happened
        assert stored.to_address == ADDRESS
        assert stored.tx_index == 0  # resolved via mocked /wallet/getblockbynum

        # Evidentiary chain: transfer -> raw_response_id -> archived body.
        raw = session.get(RawApiResponse, stored.raw_response_id)
        assert raw is not None
        assert raw.source == "trongrid"
        assert "tx1" in raw.body


def test_backfill_raises_hard_error_on_balance_mismatch(tmp_path):
    transport = httpx.MockTransport(_make_handler(node_balance=999_999))  # doesn't match ledger's 100
    db_url = f"sqlite:///{tmp_path}/case2.db"

    with pytest.raises(ReconciliationError):
        with session_scope(db_url) as session:
            backfill_address(session, ADDRESS, "TRX", ClientConfig(trongrid_api_key="test"), transport=transport)
