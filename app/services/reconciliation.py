from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database import read_transaction
from app.repositories.reconciliation import ReconciliationRepository
from app.schemas import (
    DiscrepancyFilters,
    DiscrepancyPage,
    ReconciliationSummary,
    SummaryFilters,
)


def get_summary(session: Session, filters: SummaryFilters) -> ReconciliationSummary:
    repository = ReconciliationRepository(session)
    with read_transaction(session):
        total, rows = repository.summary_page(filters)
    return ReconciliationSummary(
        group_by=filters.group_by,
        items=rows,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        total_pages=(total + filters.page_size - 1) // filters.page_size,
    )


def get_discrepancies(
    session: Session, filters: DiscrepancyFilters, grace_hours: int
) -> DiscrepancyPage:
    evaluated_at = datetime.now(UTC)
    if filters.as_of is not None:
        evaluated_at = filters.as_of.astimezone(UTC)
    repository = ReconciliationRepository(session)
    with read_transaction(session):
        total, rows = repository.discrepancy_page(filters, evaluated_at, grace_hours)
    return DiscrepancyPage(
        items=rows,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        total_pages=(total + filters.page_size - 1) // filters.page_size,
        evaluated_at=evaluated_at,
        settlement_grace_hours=grace_hours,
    )
