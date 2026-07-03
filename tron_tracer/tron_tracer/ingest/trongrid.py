"""TronGrid client (blueprint Sec 3.1-3.2).

Endpoint shapes below are based on TronGrid's documented v1 REST API as of
the 2026 documentation set (developers.tron.network). Two facts used for
canonical ordering are NOT exposed directly by the convenience endpoints
and must be independently verified against a live sandbox response before
this client is pointed at production ingestion:

  * `tx_index` (position of a transaction within its block) is not
    returned by /v1/accounts/{address}/transactions or the trc20
    variant. We derive it by fetching the full block via the full-node
    HTTP API (`/wallet/getblockbynum`, which TronGrid proxies) and using
    the transaction's position in the block's `transactions` array --
    the standard approach block explorers use.
  * `log_index` for TRC-20 transfer events is not present on
    /v1/accounts/{address}/transactions/trc20 either. We derive it from
    /v1/transactions/{id}/events, whose event objects carry an
    `event_index` field.

See ordering.py for both derivations. If live testing shows different
field names, update ordering.py/normalize.py only -- the tracing engine
downstream never depends on TronGrid's specific field names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from tron_tracer.config import ClientConfig
from tron_tracer.ingest.address import base58_to_hex
from tron_tracer.ingest.http_client import ApiClientBase, ArchiveFn, RetryExhausted


@dataclass
class Page:
    items: list[dict]
    raw_response_id: int | None
    exhausted: bool  # True if this was confirmed to be the last page


class TronGridClient(ApiClientBase):
    source_name = "trongrid"

    def __init__(self, config: ClientConfig, archive_fn: ArchiveFn | None = None, transport=None):
        super().__init__(
            base_url=config.trongrid_base_url,
            config=config,
            archive_fn=archive_fn,
            api_key_header="TRON-PRO-API-KEY",
            api_key=config.trongrid_api_key,
            transport=transport,
        )

    def get_account(self, address: str) -> tuple[dict | None, int | None]:
        result = self.get(f"/v1/accounts/{address}", params={})
        body = result.body_json or {}
        data = body.get("data") or []
        account = data[0] if data else None
        return account, result.raw_response_id

    def _paginate(self, endpoint: str, params: dict) -> Iterator[Page]:
        """Follow TronGrid's fingerprint-based cursor to exhaustion.
        Yields one Page per HTTP response; caller decides how far to go."""
        params = dict(params)
        params.setdefault("limit", self.config.page_limit)

        while True:
            result = self.get(endpoint, params=params)
            body = result.body_json or {}
            items = body.get("data") or []
            meta = body.get("meta") or {}
            next_link = (meta.get("links") or {}).get("next")
            fingerprint = meta.get("fingerprint")

            exhausted = not items or not next_link or not fingerprint
            yield Page(items=items, raw_response_id=result.raw_response_id, exhausted=exhausted)

            if exhausted:
                return
            params["fingerprint"] = fingerprint

    def iter_transactions(self, address: str, *, min_timestamp: int | None = None,
                           max_timestamp: int | None = None) -> Iterator[Page]:
        """Native/TRC-10/system-contract transactions."""
        params: dict = {"order_by": "block_timestamp,asc", "only_confirmed": "true"}
        if min_timestamp is not None:
            params["min_timestamp"] = min_timestamp
        if max_timestamp is not None:
            params["max_timestamp"] = max_timestamp
        yield from self._paginate(f"/v1/accounts/{address}/transactions", params)

    def iter_trc20_transfers(self, address: str, *, contract_address: str | None = None,
                              min_timestamp: int | None = None,
                              max_timestamp: int | None = None) -> Iterator[Page]:
        params: dict = {"order_by": "block_timestamp,asc", "only_confirmed": "true"}
        if contract_address:
            params["contract_address"] = contract_address
        if min_timestamp is not None:
            params["min_timestamp"] = min_timestamp
        if max_timestamp is not None:
            params["max_timestamp"] = max_timestamp
        yield from self._paginate(f"/v1/accounts/{address}/transactions/trc20", params)

    def get_transaction_events(self, tx_id: str) -> tuple[list[dict], int | None]:
        result = self.get(f"/v1/transactions/{tx_id}/events", params={})
        body = result.body_json or {}
        return body.get("data") or [], result.raw_response_id

    def get_trc20_balance(self, owner_address: str, contract_address: str) -> tuple[int, int | None]:
        """Read the on-chain TRC-20 balance via a constant (read-only)
        contract call -- used only for the ingestion-completeness
        reconciliation check (blueprint Sec 3.4), never for tracing."""
        owner_hex = base58_to_hex(owner_address)
        contract_hex = base58_to_hex(contract_address)
        # ABI-encode a single `address` argument: 20-byte account, left-padded to 32 bytes.
        account_hex = owner_hex[2:] if owner_hex.startswith("41") else owner_hex
        parameter = account_hex.rjust(64, "0")

        result = self.post(
            "/wallet/triggerconstantcontract",
            json_body={
                "owner_address": owner_hex,
                "contract_address": contract_hex,
                "function_selector": "balanceOf(address)",
                "parameter": parameter,
                "visible": False,
            },
        )
        body = result.body_json or {}
        constant_result = body.get("constant_result") or []
        if not constant_result:
            raise RetryExhausted(f"triggerconstantcontract returned no result: {body}")
        return int(constant_result[0], 16), result.raw_response_id

    def get_block_by_num(self, block_number: int) -> tuple[dict | None, int | None]:
        # POST-only full-node endpoint (TronGrid proxies java-tron's HTTP API).
        result = self.post("/wallet/getblockbynum", json_body={"num": block_number})
        body = result.body_json
        if not body:
            return None, result.raw_response_id
        return body, result.raw_response_id
