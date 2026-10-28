"""SQLAlchemy query expressions for database-side report aggregation."""

from datetime import datetime, timedelta

from sqlalchemy import (
    Date,
    DateTime,
    Interval,
    Text,
    and_,
    any_,
    case,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session

from app.models import Merchant, Transaction
from app.schemas import DiscrepancyFilters, ReconciliationFilters, SummaryFilters


def report_conditions(filters: ReconciliationFilters):
    conditions = []
    if filters.merchant_id is not None:
        conditions.append(Transaction.merchant_id == filters.merchant_id)
    if filters.date_from is not None:
        conditions.append(Transaction.first_event_at >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Transaction.first_event_at < filters.date_to)
    return conditions


class ReconciliationRepository:
    def __init__(self, session: Session):
        self.session = session

    def summary_page(self, filters: SummaryFilters):
        # Choose the grouping column; keep currencies separate in every report.
        name = literal(None, Text)
        if filters.group_by == 'merchant':
            group = Transaction.merchant_id
            name = Merchant.merchant_name
        elif filters.group_by == 'date':
            utc_date = cast(func.timezone('UTC', Transaction.first_event_at), Date)
            group = cast(utc_date, Text)
        else:
            group = Transaction.payment_status
        grouped = (
            select(
                group.label('group_value'),
                name.label('merchant_name'),
                Transaction.currency,
                func.count().label('transaction_count'),
                func.count()
                .filter(Transaction.payment_status == 'processed')
                .label('processed_count'),
                func.count()
                .filter(Transaction.payment_status == 'failed')
                .label('failed_count'),
                func.count()
                .filter(Transaction.payment_status == 'conflict')
                .label('conflict_count'),
                func.count()
                .filter(Transaction.settlement_status == 'settled')
                .label('settled_count'),
                func.count()
                .filter(
                    and_(
                        Transaction.payment_status == 'processed',
                        Transaction.settlement_status == 'pending',
                    )
                )
                .label('pending_settlement_count'),
                func.sum(Transaction.amount).label('total_amount'),
                func.coalesce(
                    func.sum(Transaction.amount).filter(
                        Transaction.settlement_status == 'settled'
                    ),
                    0,
                ).label('settled_amount'),
            )
            .join(Merchant)
            .where(*report_conditions(filters))
            .group_by(group, name, Transaction.currency)
            .cte('grouped')
        )
        total = self.session.scalar(select(func.count()).select_from(grouped))
        statement = (
            select(grouped)
            .order_by(grouped.c.group_value, grouped.c.currency)
            .limit(filters.page_size)
            .offset((filters.page - 1) * filters.page_size)
        )
        result = self.session.execute(statement)
        rows = result.mappings().all()
        return total, rows

    def discrepancy_page(
        self, filters: DiscrepancyFilters, evaluated_at: datetime, grace_hours: int
    ):
        # Subtraction stays in SQL, retaining PostgreSQL's timestamp range.
        cutoff = literal(evaluated_at, DateTime(timezone=True)) - literal(
            timedelta(hours=grace_hours), Interval
        )
        # Each condition below is evaluated by PostgreSQL for each transaction.
        overdue = and_(
            Transaction.payment_status == 'processed',
            Transaction.settlement_status == 'pending',
            Transaction.processed_at < cutoff,
        )
        settled_failed = and_(
            Transaction.payment_status.in_(['failed', 'conflict']),
            Transaction.settlement_status == 'settled',
        )
        conflicting_events = Transaction.payment_status == 'conflict'
        settled_without_processing = and_(
            Transaction.payment_status.in_(['unknown', 'initiated']),
            Transaction.settlement_status == 'settled',
        )

        # CASE returns the reason when true, or NULL otherwise.
        possible_reasons = array(
            [
                case((overdue, 'overdue_settlement')),
                case((settled_failed, 'settled_failed_payment')),
                case((conflicting_events, 'conflicting_payment_events')),
                case(
                    (settled_without_processing, 'settlement_without_processed_payment')
                ),
            ],
            type_=Text,
        )
        reasons = func.array_remove(possible_reasons, None).label('reasons')
        # A named SQL result lets us filter reasons before counting and paging.
        flagged = (
            select(Transaction, reasons)
            .where(*report_conditions(filters))
            .cte('flagged')
        )
        conditions = [func.cardinality(flagged.c.reasons) > 0]
        if filters.reason is not None:
            conditions.append(literal(filters.reason) == any_(flagged.c.reasons))
        total = self.session.scalar(
            select(func.count()).select_from(flagged).where(*conditions)
        )
        statement = (
            select(*flagged.c, Merchant.merchant_name)
            .join(Merchant, Merchant.merchant_id == flagged.c.merchant_id)
            .where(*conditions)
            .order_by(flagged.c.first_event_at.desc(), flagged.c.transaction_id.desc())
            .limit(filters.page_size)
            .offset((filters.page - 1) * filters.page_size)
        )
        result = self.session.execute(statement)
        rows = result.mappings().all()
        return total, rows
