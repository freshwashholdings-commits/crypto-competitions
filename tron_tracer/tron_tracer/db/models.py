"""Normalized schema per blueprint Section 4.

Amounts are arbitrary-precision integers in the asset's smallest unit
(sun for TRX). They are stored as TEXT and marshalled to/from Python
`int` by `SunInt` so behavior is identical on SQLite and Postgres --
never a native float or a fixed-precision NUMERIC that could silently
truncate a very large TRC-10/TRC-20 balance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SunInt(TypeDecorator):
    """Arbitrary-precision integer stored as TEXT; never a float."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, int):
            raise TypeError(f"SunInt requires a Python int, got {type(value)!r}")
        return str(value)

    def process_result_value(self, value: str | None, dialect) -> int | None:
        if value is None:
            return None
        return int(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# SQLite only aliases a primary key column to its auto-incrementing rowid
# when the column's declared type is literally INTEGER; BIGINT (used for
# Postgres BIGSERIAL parity) does not qualify, which silently breaks
# autoincrement on SQLite. Use INTEGER there, BIGINT everywhere else.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class RawApiResponse(Base):
    """Archived, hashed copy of every API response. The evidentiary root:
    chain -> archived API response (this table) -> normalized row."""

    __tablename__ = "raw_api_responses"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'trongrid' | 'tronscan' | 'fullnode'
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_raw_api_responses_source_endpoint", "source", "endpoint"),
        Index("ix_raw_api_responses_sha256", "sha256"),
    )


class Transfer(Base):
    """Every on-chain value movement, all asset types unified."""

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tx_hash: Mapped[str] = mapped_column(String, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # ms epoch, display only
    from_address: Mapped[str] = mapped_column(String, nullable=False)
    to_address: Mapped[str] = mapped_column(String, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)  # TRX | TRC20 | TRC10 | INTERNAL
    asset_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(SunInt, nullable=False)
    fee_sun: Mapped[int] = mapped_column(SunInt, nullable=False, default=0)
    contract_type: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_response_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_api_responses.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", "asset_type", "asset_id", name="uq_transfer_identity"),
        Index("ix_transfers_from", "from_address", "asset_id", "block_number", "tx_index", "log_index"),
        Index("ix_transfers_to", "to_address", "asset_id", "block_number", "tx_index", "log_index"),
    )

    @property
    def order_key(self) -> tuple[int, int, int]:
        return (self.block_number, self.tx_index, self.log_index)


class Account(Base):
    __tablename__ = "accounts"

    address: Mapped[str] = mapped_column(String, primary_key=True)
    is_contract: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    activation_tx: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_permission: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active_permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    snapshot_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_response_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_api_responses.id"), nullable=True
    )


class Label(Base):
    """Exchange/service tags. Leads, not evidence -- always carry provenance."""

    __tablename__ = "labels"

    address: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)


class AddressLink(Base):
    """Attribution engine output. This is an INFERENCE, never a fact."""

    __tablename__ = "address_links"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    address_a: Mapped[str] = mapped_column(String, nullable=False)
    address_b: Mapped[str] = mapped_column(String, nullable=False)
    link_type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    signals: Mapped[list] = mapped_column(JSON, nullable=False)
    method_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_address_links_a", "address_a"),
        Index("ix_address_links_b", "address_b"),
    )


class AuditLogEntry(Base):
    """Hash-chained, append-only. See tron_tracer.audit.audit_log."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    this_hash: Mapped[str] = mapped_column(String, nullable=False)
