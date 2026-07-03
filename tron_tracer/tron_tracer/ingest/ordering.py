"""Derives the two ordering fields TronGrid's convenience endpoints don't
expose directly: `tx_index` (position of a tx within its block) and
`log_index` (position of a TRC-20 Transfer event within its tx's event
log). See trongrid.py module docstring for why these need derivation and
what to re-verify against a live response.
"""

from __future__ import annotations

from tron_tracer.ingest.trongrid import TronGridClient


class BlockIndexResolver:
    """Caches block -> {tx_hash: position} so tracing a busy address doesn't
    refetch the same block once per transaction."""

    def __init__(self, client: TronGridClient):
        self._client = client
        self._cache: dict[int, dict[str, int]] = {}

    def tx_index(self, block_number: int, tx_hash: str) -> int:
        positions = self._cache.get(block_number)
        if positions is None:
            positions = self._load_block(block_number)
            self._cache[block_number] = positions
        if tx_hash not in positions:
            raise KeyError(
                f"tx {tx_hash} not found in block {block_number}'s transaction list; "
                "block may have been reorganized or the archived response is stale"
            )
        return positions[tx_hash]

    def _load_block(self, block_number: int) -> dict[str, int]:
        block, _raw_id = self._client.get_block_by_num(block_number)
        if not block:
            raise ValueError(f"block {block_number} not found")
        txs = block.get("transactions") or []
        positions: dict[str, int] = {}
        for idx, tx in enumerate(txs):
            tx_hash = tx.get("txID") or tx.get("tx_id") or tx.get("hash")
            if tx_hash:
                positions[tx_hash] = idx
        return positions


class EventIndexResolver:
    """Caches tx_hash -> {contract_address+recipient+value occurrence: event_index}
    is overkill; instead we cache the ordered event list per tx and match by
    position among same-named events, falling back to enumerate() order if
    the API's `event_index` field is absent."""

    def __init__(self, client: TronGridClient):
        self._client = client
        self._cache: dict[str, list[dict]] = {}

    def events_for_tx(self, tx_hash: str) -> list[dict]:
        events = self._cache.get(tx_hash)
        if events is None:
            events, _raw_id = self._client.get_transaction_events(tx_hash)
            self._cache[tx_hash] = events
        return events

    def log_index(self, tx_hash: str, *, event_name: str, occurrence: int) -> int:
        """`occurrence` is the 0-based position of this Transfer event among
        all events TronGrid returned for the tx, in the order TronGrid
        returned them (used to disambiguate when explicit event_index is
        absent from the archived response)."""
        events = self.events_for_tx(tx_hash)
        matches = [(idx, e) for idx, e in enumerate(events) if e.get("event_name") == event_name]
        if occurrence >= len(matches):
            return occurrence  # can't disambiguate; caller's fallback ordinal
        raw_position, candidate = matches[occurrence]
        event_index = candidate.get("event_index")
        return int(event_index) if event_index is not None else raw_position
