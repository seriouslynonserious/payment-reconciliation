from typing import Annotated

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.database import get_session
from app.schemas import DiscrepancyFilters, DiscrepancyPage, ReconciliationSummary, SummaryFilters
from app.services.reconciliation import get_discrepancies, get_summary

router = APIRouter(prefix='/reconciliation', tags=['Reconciliation'])
Database = Annotated[Session, Depends(get_session)]


@router.get('/summary', response_model=ReconciliationSummary)
def reconciliation_summary(
    filters: Annotated[SummaryFilters, Query()], session: Database,
) -> ReconciliationSummary:
    """Group current transaction state by merchant, UTC first-event date, or payment status.

    Currency is always a separate grouping dimension. Total counts groups, not transactions.
    """
    return get_summary(session, filters)


@router.get('/discrepancies', response_model=DiscrepancyPage)
def reconciliation_discrepancies(
    filters: Annotated[DiscrepancyFilters, Query()], session: Database,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiscrepancyPage:
    """List inconsistent transactions with reasons; overdue means strictly beyond the grace period.

    as_of controls the aging clock only, not historical state reconstruction.
    Without as_of, the current UTC time is used. Identical retries are not discrepancies.
    """
    return get_discrepancies(session, filters, settings.settlement_grace_hours)
