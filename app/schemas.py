from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class PaymentEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    event_id: UUID
    event_type: Literal[
        'payment_initiated', 'payment_processed', 'payment_failed', 'settled'
    ]
    transaction_id: UUID
    merchant_id: str = Field(min_length=1, max_length=100)
    merchant_name: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    timestamp: AwareDatetime

    @field_validator('timestamp')
    @classmethod
    def normalize_timestamp(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    def canonical_payload(self) -> dict:
        # Normalize values so 10 and 10.00 count as the same retry.
        payload = self.model_dump(mode='json')
        payload['amount'] = format(self.amount, '.2f')
        return payload


class IngestionResult(BaseModel):
    event_id: UUID
    transaction_id: UUID
    duplicate: bool
    payment_status: Literal['unknown', 'initiated', 'processed', 'failed', 'conflict']
    settlement_status: Literal['pending', 'settled']


class TransactionFilters(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    merchant_id: str | None = Field(default=None, min_length=1, max_length=100)
    status: (
        Literal['unknown', 'initiated', 'processed', 'failed', 'conflict'] | None
    ) = None
    settlement_status: Literal['pending', 'settled'] | None = None
    date_from: AwareDatetime | None = None
    date_to: AwareDatetime | None = None
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: Literal['first_event_at', 'created_at', 'amount', 'payment_status'] = (
        'first_event_at'
    )
    sort_order: Literal['asc', 'desc'] = 'desc'

    @model_validator(mode='after')
    def validate_date_range(self) -> 'TransactionFilters':
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from >= self.date_to
        ):
            raise ValueError('date_from must be earlier than date_to')
        return self


class TransactionSummary(BaseModel):
    transaction_id: UUID
    merchant_id: str
    merchant_name: str
    amount: Decimal
    currency: str
    payment_status: Literal['unknown', 'initiated', 'processed', 'failed', 'conflict']
    settlement_status: Literal['pending', 'settled']
    first_event_at: datetime
    last_event_at: datetime
    processed_at: datetime | None
    settled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class EventHistoryItem(BaseModel):
    event_id: UUID
    event_type: Literal[
        'payment_initiated', 'payment_processed', 'payment_failed', 'settled'
    ]
    event_timestamp: datetime
    received_at: datetime
    payload: dict


class TransactionDetail(TransactionSummary):
    events: list[EventHistoryItem]


DiscrepancyReason = Literal[
    'overdue_settlement',
    'settled_failed_payment',
    'conflicting_payment_events',
    'settlement_without_processed_payment',
]


class ReconciliationFilters(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    merchant_id: str | None = Field(default=None, min_length=1, max_length=100)
    date_from: AwareDatetime | None = None
    date_to: AwareDatetime | None = None
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode='after')
    def validate_date_range(self) -> 'ReconciliationFilters':
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from >= self.date_to
        ):
            raise ValueError('date_from must be earlier than date_to')
        return self


class SummaryFilters(ReconciliationFilters):
    group_by: Literal['merchant', 'date', 'status'] = 'merchant'


class SummaryGroup(BaseModel):
    group_value: str
    merchant_name: str | None
    currency: str
    transaction_count: int
    processed_count: int
    failed_count: int
    conflict_count: int
    settled_count: int
    pending_settlement_count: int
    total_amount: Decimal
    settled_amount: Decimal


class ReconciliationSummary(BaseModel):
    group_by: Literal['merchant', 'date', 'status']
    items: list[SummaryGroup]
    total: int
    page: int
    page_size: int
    total_pages: int


class DiscrepancyFilters(ReconciliationFilters):
    reason: DiscrepancyReason | None = None
    as_of: AwareDatetime | None = None


class DiscrepancyItem(TransactionSummary):
    reasons: list[DiscrepancyReason]


class DiscrepancyPage(BaseModel):
    items: list[DiscrepancyItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    evaluated_at: datetime
    settlement_grace_hours: int
