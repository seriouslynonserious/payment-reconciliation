from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database import read_transaction
from app.repositories.reconciliation import ReconciliationRepository
from app.schemas import DiscrepancyFilters, DiscrepancyPage, ReconciliationSummary, SummaryFilters


def get_summary(session: Session, filters: SummaryFilters) -> ReconciliationSummary:
    with read_transaction(session):
        total, rows = ReconciliationRepository(session).summary_page(filters)
    return ReconciliationSummary(group_by=filters.group_by, items=rows, total=total,
        page=filters.page, page_size=filters.page_size,
        total_pages=(total + filters.page_size - 1) // filters.page_size)


def get_discrepancies(session: Session, filters: DiscrepancyFilters, grace_hours: int) -> DiscrepancyPage:
    evaluated_at = (filters.as_of or datetime.now(UTC)).astimezone(UTC)
    with read_transaction(session):
        total, rows = ReconciliationRepository(session).discrepancy_page(filters, evaluated_at, grace_hours)
    return DiscrepancyPage(items=rows, total=total, page=filters.page, page_size=filters.page_size,
        total_pages=(total + filters.page_size - 1) // filters.page_size,
        evaluated_at=evaluated_at, settlement_grace_hours=grace_hours)
