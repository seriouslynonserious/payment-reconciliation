"""ORM mappings for the existing schema. SQL migrations own table creation."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = 'merchants'
    merchant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    merchant_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = 'transactions'
    transaction_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey('merchants.merchant_id', ondelete='RESTRICT'))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    payment_status: Mapped[str] = mapped_column(Text, server_default=text("'unknown'"))
    settlement_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    first_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentEventRecord(Base):
    __tablename__ = 'payment_events'
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey('transactions.transaction_id', ondelete='RESTRICT'))
    event_type: Mapped[str] = mapped_column(Text)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB)
