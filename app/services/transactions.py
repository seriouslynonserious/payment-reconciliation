from uuid import UUID

from sqlalchemy.orm import Session

from app.database import read_transaction
from app.repositories.events import EventRepository
from app.repositories.transactions import TransactionRepository
from app.schemas import TransactionDetail, TransactionFilters, TransactionPage


def list_transactions(session: Session, filters: TransactionFilters) -> TransactionPage:
    repository = TransactionRepository(session)
    with read_transaction(session):
        total, rows = repository.list_page(filters)
    # Round up: 21 rows with page size 20 need two pages.
    return TransactionPage(
        items=rows,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        total_pages=(total + filters.page_size - 1) // filters.page_size,
    )


def get_transaction(session: Session, transaction_id: UUID) -> TransactionDetail | None:
    repository = TransactionRepository(session)
    with read_transaction(session):
        row = repository.find_details(transaction_id)
        if row is None:
            return None
        events = EventRepository(session).history(transaction_id)
    return TransactionDetail(**row, events=events)
