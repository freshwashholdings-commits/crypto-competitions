"""SQLAlchemy-backed TransferProvider for real case databases (the
`trace.py` CLI deliverable, blueprint Sec 9 Phase 2)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tron_tracer.db.models import Account, Label, Transfer
from tron_tracer.trace.tranche import TransferRecord


class DbTransferProvider:
    def __init__(self, session: Session):
        self.session = session

    def transfers_touching(self, address: str) -> list[TransferRecord]:
        rows = self.session.execute(
            select(Transfer).where(or_(Transfer.from_address == address, Transfer.to_address == address))
        ).scalars().all()
        return [
            TransferRecord(
                tx_hash=r.tx_hash, block_number=r.block_number, tx_index=r.tx_index, log_index=r.log_index,
                block_timestamp=r.block_timestamp, from_address=r.from_address, to_address=r.to_address,
                asset_type=r.asset_type, asset_id=r.asset_id, amount=r.amount, fee_sun=r.fee_sun,
                contract_type=r.contract_type,
            )
            for r in rows
        ]

    def is_labeled_service(self, address: str) -> bool:
        return self.session.execute(select(Label).where(Label.address == address).limit(1)).scalar_one_or_none() is not None

    def is_contract(self, address: str) -> bool:
        acct = self.session.get(Account, address)
        return bool(acct and acct.is_contract)

    def opening_balance(self, address: str, asset_id: str) -> int:
        return 0  # v1: full history is always replayed (blueprint Sec 3.4 completeness check)

    def transfer_by_tx(self, tx_hash: str, asset_id: str) -> TransferRecord | None:
        row = self.session.execute(
            select(Transfer).where(Transfer.tx_hash == tx_hash, Transfer.asset_id == asset_id)
        ).scalars().first()
        if row is None:
            return None
        return TransferRecord(
            tx_hash=row.tx_hash, block_number=row.block_number, tx_index=row.tx_index, log_index=row.log_index,
            block_timestamp=row.block_timestamp, from_address=row.from_address, to_address=row.to_address,
            asset_type=row.asset_type, asset_id=row.asset_id, amount=row.amount, fee_sun=row.fee_sun,
            contract_type=row.contract_type,
        )
