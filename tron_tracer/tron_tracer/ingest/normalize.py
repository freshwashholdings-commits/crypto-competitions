"""Raw TronGrid JSON -> normalized dict rows ready for `transfers`/`accounts`.

Kept as pure functions (raw dict in, list[dict] out) rather than ORM
writes so they're unit-testable against fixture JSON without a database,
per the golden-test philosophy in blueprint Sec 5.4.
"""

from __future__ import annotations

from tron_tracer.config import TRX_ASSET_ID
from tron_tracer.ingest.address import normalize_address
from tron_tracer.ingest.ordering import BlockIndexResolver, EventIndexResolver

NATIVE_VALUE_CONTRACTS = {"TransferContract", "TransferAssetContract"}


def normalize_account(address: str, raw: dict | None, snapshot_block: int | None,
                       raw_response_id: int | None) -> dict:
    if raw is None:
        return {
            "address": address,
            "is_contract": None,
            "created_block": None,
            "owner_permission": None,
            "active_permissions": None,
            "snapshot_block": snapshot_block,
            "raw_response_id": raw_response_id,
        }
    return {
        "address": address,
        "is_contract": bool(raw.get("type") == "Contract" or raw.get("is_contract")),
        "created_block": raw.get("create_block") or raw.get("latest_operation_block"),
        "owner_permission": raw.get("owner_permission"),
        "active_permissions": raw.get("active_permission"),
        "snapshot_block": snapshot_block,
        "raw_response_id": raw_response_id,
    }


def normalize_native_transactions(
    tx_items: list[dict],
    block_resolver: BlockIndexResolver,
    raw_response_id: int | None,
) -> list[dict]:
    """Extract TRX/TRC-10 value-moving contracts from a page of
    /v1/accounts/{address}/transactions results. Contract-trigger calls
    (DEX/bridge interactions) are recorded elsewhere as terminal markers,
    not decoded here -- see blueprint Sec 3.3/10."""
    rows: list[dict] = []

    for tx in tx_items:
        tx_hash = tx.get("txID") or tx.get("tx_id")
        block_number = tx.get("blockNumber") or tx.get("block_number")
        block_timestamp = tx.get("block_timestamp") or (tx.get("raw_data") or {}).get("timestamp") or 0
        raw_data = tx.get("raw_data") or {}
        contracts = raw_data.get("contract") or []
        rets = tx.get("ret") or []

        if tx_hash is None or block_number is None:
            continue

        tx_index = block_resolver.tx_index(int(block_number), tx_hash)

        for i, contract in enumerate(contracts):
            ctype = contract.get("type")
            if ctype not in NATIVE_VALUE_CONTRACTS:
                continue
            value = (contract.get("parameter") or {}).get("value") or {}
            fee = 0
            if i < len(rets):
                ret = rets[i]
                if ret.get("contractRet") != "SUCCESS":
                    continue
                fee = int(ret.get("fee") or 0)

            if ctype == "TransferContract":
                asset_type, asset_id, amount_key = "TRX", TRX_ASSET_ID, "amount"
            else:  # TransferAssetContract (TRC-10)
                asset_type = "TRC10"
                asset_id = value.get("asset_name", "")
                amount_key = "amount"

            owner = value.get("owner_address")
            to = value.get("to_address")
            amount = value.get(amount_key)
            if owner is None or to is None or amount is None:
                continue

            rows.append({
                "tx_hash": tx_hash,
                "block_number": int(block_number),
                "tx_index": tx_index,
                "log_index": 0,
                "block_timestamp": int(block_timestamp),
                "from_address": normalize_address(owner),
                "to_address": normalize_address(to),
                "asset_type": asset_type,
                "asset_id": asset_id,
                "amount": int(amount),
                "fee_sun": fee,
                "contract_type": ctype,
                "raw_response_id": raw_response_id,
            })

    return rows


def normalize_trc20_transfers(
    items: list[dict],
    block_resolver: BlockIndexResolver,
    event_resolver: EventIndexResolver,
    raw_response_id: int | None,
) -> list[dict]:
    rows: list[dict] = []
    occurrence_by_tx: dict[str, int] = {}

    for item in items:
        if item.get("type") not in (None, "Transfer"):
            continue  # skip Approval and other TRC-20 event types
        tx_hash = item.get("transaction_id") or item.get("transaction_hash")
        block_number = item.get("block_number")
        block_timestamp = item.get("block_timestamp")
        from_addr = item.get("from")
        to_addr = item.get("to")
        value = item.get("value")
        token_info = item.get("token_info") or {}
        contract_address = token_info.get("address") or item.get("contract_address")

        if not all([tx_hash, from_addr, to_addr, value is not None, contract_address]):
            continue

        occurrence = occurrence_by_tx.get(tx_hash, 0)
        occurrence_by_tx[tx_hash] = occurrence + 1

        if block_number is None:
            block_number = _block_number_from_events(event_resolver, tx_hash)
        tx_index = block_resolver.tx_index(int(block_number), tx_hash)
        log_index = event_resolver.log_index(tx_hash, event_name="Transfer", occurrence=occurrence)

        rows.append({
            "tx_hash": tx_hash,
            "block_number": int(block_number),
            "tx_index": tx_index,
            "log_index": log_index,
            "block_timestamp": int(block_timestamp or 0),
            "from_address": normalize_address(from_addr),
            "to_address": normalize_address(to_addr),
            "asset_type": "TRC20",
            "asset_id": contract_address,
            "amount": int(value),
            "fee_sun": 0,
            "contract_type": "TriggerSmartContract",
            "raw_response_id": raw_response_id,
        })

    return rows


def _block_number_from_events(event_resolver: EventIndexResolver, tx_hash: str) -> int:
    events = event_resolver.events_for_tx(tx_hash)
    for e in events:
        if e.get("block_number") is not None:
            return int(e["block_number"])
    raise ValueError(f"could not determine block_number for tx {tx_hash}")
