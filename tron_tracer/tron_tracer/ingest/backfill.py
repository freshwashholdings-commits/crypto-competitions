"""Ingestion orchestration: `ingest.py backfill <address> --asset USDT`
(blueprint Sec 9 Phase 1 deliverable).

Populates `accounts` and `transfers`, then runs the mandatory balance
reconciliation check (Sec 3.4): computed balance (in - out - fees) must
match the node-reported balance at the snapshot block, or ingestion
fails hard. For TRX this can be legitimately thrown off by staking,
voting, and resource-delegation operations that move balance outside
plain transfers -- that is a documented v1 scope boundary (Sec 10), not
silently ignored: the reconciliation error message says so explicitly
rather than passing a wrong number through as if it were verified.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from tron_tracer.config import USDT_TRC20_CONTRACT, TRX_ASSET_ID, ClientConfig
from tron_tracer.db.models import Account, Transfer
from tron_tracer.ingest.archive import make_db_archive_fn
from tron_tracer.ingest.normalize import (
    normalize_account,
    normalize_native_transactions,
    normalize_trc20_transfers,
)
from tron_tracer.ingest.ordering import BlockIndexResolver, EventIndexResolver
from tron_tracer.ingest.trongrid import TronGridClient
from tron_tracer.audit.audit_log import append_entry


class ReconciliationError(RuntimeError):
    pass


@dataclass
class BackfillResult:
    address: str
    asset_id: str
    native_rows_ingested: int
    trc20_rows_ingested: int
    snapshot_block: int | None
    reconciled: bool
    computed_balance: int | None
    node_balance: int | None


def _existing_keys(session: Session, tx_hashes: set[str]) -> set[tuple[str, int, str, str]]:
    if not tx_hashes:
        return set()
    rows = session.execute(
        select(Transfer.tx_hash, Transfer.log_index, Transfer.asset_type, Transfer.asset_id)
        .where(Transfer.tx_hash.in_(tx_hashes))
    ).all()
    return {tuple(r) for r in rows}


def _insert_new_transfers(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    existing = _existing_keys(session, {r["tx_hash"] for r in rows})
    inserted = 0
    for row in rows:
        key = (row["tx_hash"], row["log_index"], row["asset_type"], row["asset_id"])
        if key in existing:
            continue
        session.add(Transfer(**row))
        existing.add(key)
        inserted += 1
    session.flush()
    return inserted


def backfill_address(
    session: Session,
    address: str,
    asset: str,
    config: ClientConfig | None = None,
    *,
    reconcile: bool = True,
    transport=None,
) -> BackfillResult:
    config = config or ClientConfig()
    archive_fn = make_db_archive_fn(session)
    client = TronGridClient(config, archive_fn=archive_fn, transport=transport)
    block_resolver = BlockIndexResolver(client)
    event_resolver = EventIndexResolver(client)

    contract_address = USDT_TRC20_CONTRACT if asset.upper() == "USDT" else (
        None if asset.upper() == "TRX" else asset
    )

    append_entry(session, "ingest_start", {"address": address, "asset": asset})

    account_raw, account_raw_id = client.get_account(address)
    snapshot_block = None
    node_balance = None
    if account_raw is not None:
        node_balance = account_raw.get("balance")
        snapshot_block = account_raw.get("latest_operation_block") or account_raw.get("create_block")
    session.merge(Account(**normalize_account(address, account_raw, snapshot_block, account_raw_id)))
    session.flush()

    native_inserted = 0
    if contract_address is None:  # TRX (and incidentally TRC-10) backfill
        for page in client.iter_transactions(address):
            rows = normalize_native_transactions(page.items, block_resolver, page.raw_response_id)
            native_inserted += _insert_new_transfers(session, rows)

    trc20_inserted = 0
    if contract_address is not None:
        for page in client.iter_trc20_transfers(address, contract_address=contract_address):
            rows = normalize_trc20_transfers(page.items, block_resolver, event_resolver, page.raw_response_id)
            trc20_inserted += _insert_new_transfers(session, rows)

    reconciled = False
    computed_balance = None
    if reconcile:
        asset_id = TRX_ASSET_ID if contract_address is None else contract_address
        computed_balance = _computed_balance(session, address, asset_id, include_fees=(contract_address is None))

        if contract_address is None:
            check_against = node_balance
        else:
            check_against, _raw_id = client.get_trc20_balance(address, contract_address)

        if check_against is not None and computed_balance != check_against:
            append_entry(session, "ingest_reconciliation_failed", {
                "address": address, "asset_id": asset_id,
                "computed_balance": computed_balance, "node_balance": check_against,
            })
            raise ReconciliationError(
                f"balance mismatch for {address} / {asset_id}: computed={computed_balance} "
                f"node_reported={check_against}. For TRX this can legitimately result from "
                f"staking/voting/resource-delegation activity not modeled as plain transfers "
                f"in v1 (blueprint Sec 10) -- do not use this address/asset for tracing until "
                f"reviewed manually."
            )
        reconciled = check_against is not None
        node_balance = check_against

    client.close()

    append_entry(session, "ingest_complete", {
        "address": address, "asset": asset,
        "native_rows_ingested": native_inserted, "trc20_rows_ingested": trc20_inserted,
        "reconciled": reconciled,
    })

    return BackfillResult(
        address=address,
        asset_id=(TRX_ASSET_ID if contract_address is None else contract_address),
        native_rows_ingested=native_inserted,
        trc20_rows_ingested=trc20_inserted,
        snapshot_block=snapshot_block,
        reconciled=reconciled,
        computed_balance=computed_balance,
        node_balance=node_balance,
    )


def _computed_balance(session: Session, address: str, asset_id: str, *, include_fees: bool) -> int:
    inbound = session.execute(
        select(Transfer).where(Transfer.to_address == address, Transfer.asset_id == asset_id)
    ).scalars().all()
    outbound = session.execute(
        select(Transfer).where(Transfer.from_address == address, Transfer.asset_id == asset_id)
    ).scalars().all()
    total_in = sum(t.amount for t in inbound)
    total_out = sum(t.amount for t in outbound)
    total_fees = sum(t.fee_sun for t in outbound) if include_fees else 0
    return total_in - total_out - total_fees
