import pytest

from tron_tracer.trace.tranche import TransferRecord


def make_transfer(
    tx_hash: str,
    block_number: int,
    tx_index: int,
    from_address: str,
    to_address: str,
    amount: int,
    *,
    log_index: int = 0,
    block_timestamp: int = 0,
    asset_type: str = "TRX",
    asset_id: str = "TRX",
    fee_sun: int = 0,
    contract_type: str | None = "TransferContract",
) -> TransferRecord:
    return TransferRecord(
        tx_hash=tx_hash,
        block_number=block_number,
        tx_index=tx_index,
        log_index=log_index,
        block_timestamp=block_timestamp,
        from_address=from_address,
        to_address=to_address,
        asset_type=asset_type,
        asset_id=asset_id,
        amount=amount,
        fee_sun=fee_sun,
        contract_type=contract_type,
    )


@pytest.fixture
def xfer():
    return make_transfer
