from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Merchant, Transaction
from app.schemas import PaymentEvent, TransactionFilters

TRANSACTION_COLUMNS = (
    Transaction.transaction_id,
    Transaction.merchant_id,
    Merchant.merchant_name,
    Transaction.amount,
    Transaction.currency,
    Transaction.payment_status,
    Transaction.settlement_status,
    Transaction.first_event_at,
    Transaction.last_event_at,
    Transaction.processed_at,
    Transaction.settled_at,
    Transaction.created_at,
    Transaction.updated_at,
)
SORT_COLUMNS = {
    'first_event_at': Transaction.first_event_at,
    'created_at': Transaction.created_at,
    'amount': Transaction.amount,
    'payment_status': Transaction.payment_status,
}


class TransactionRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_exists(self, event: PaymentEvent) -> None:
        statement = insert(Transaction).values(
            transaction_id=event.transaction_id,
            merchant_id=event.merchant_id,
            amount=event.amount,
            currency=event.currency,
            first_event_at=event.timestamp,
            last_event_at=event.timestamp,
        )
        self.session.execute(
            statement.on_conflict_do_nothing(index_elements=['transaction_id'])
        )

    def find_by_id(
        self, transaction_id: UUID, *, for_update: bool = False
    ) -> Transaction:
        statement = select(Transaction).where(
            Transaction.transaction_id == transaction_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.execute(
            statement.execution_options(populate_existing=True)
        ).scalar_one()

    def update_state(self, transaction_id: UUID, values: dict) -> None:
        self.session.execute(
            update(Transaction)
            .where(Transaction.transaction_id == transaction_id)
            .values(**values, updated_at=func.clock_timestamp())
        )

    def find_details(self, transaction_id: UUID):
        statement = (
            select(*TRANSACTION_COLUMNS)
            .join(Merchant)
            .where(Transaction.transaction_id == transaction_id)
        )
        return self.session.execute(statement).mappings().one_or_none()

    def list_page(self, filters: TransactionFilters):
        conditions = []
        # Add only the filters supplied by the caller.
        if filters.merchant_id is not None:
            conditions.append(Transaction.merchant_id == filters.merchant_id)
        if filters.status is not None:
            conditions.append(Transaction.payment_status == filters.status)
        if filters.settlement_status is not None:
            conditions.append(
                Transaction.settlement_status == filters.settlement_status
            )
        if filters.date_from is not None:
            conditions.append(Transaction.first_event_at >= filters.date_from)
        if filters.date_to is not None:
            conditions.append(Transaction.first_event_at < filters.date_to)
        total = self.session.scalar(
            select(func.count()).select_from(Transaction).where(*conditions)
        )
        column = SORT_COLUMNS[filters.sort_by]
        # The ID breaks ties so pagination has a stable order.
        if filters.sort_order == 'asc':
            order = (column.asc(), Transaction.transaction_id.asc())
        else:
            order = (column.desc(), Transaction.transaction_id.desc())
        statement = (
            select(*TRANSACTION_COLUMNS)
            .join(Merchant)
            .where(*conditions)
            .order_by(*order)
            .limit(filters.page_size)
            .offset((filters.page - 1) * filters.page_size)
        )
        return total, self.session.execute(statement).mappings().all()
