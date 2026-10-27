from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import PaymentEventRecord as Event
from app.schemas import PaymentEvent


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_id(self, event_id: UUID) -> None:
        # A transaction-scoped lock also protects the same ID sent for different payments.
        self.session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))'),
                             {'id': str(event_id)})

    def find_by_id(self, event_id: UUID) -> Event | None:
        return self.session.get(Event, event_id)

    def add(self, event: PaymentEvent, payload: dict) -> None:
        self.session.add(Event(event_id=event.event_id, transaction_id=event.transaction_id,
            event_type=event.event_type, event_timestamp=event.timestamp, payload=payload))
        # Ensure the aggregate below includes this new event; this does not commit.
        self.session.flush()

    def aggregate_history(self, transaction_id: UUID):
        statement = select(
            func.bool_or(Event.event_type == 'payment_initiated').label('initiated'),
            func.bool_or(Event.event_type == 'payment_processed').label('processed'),
            func.bool_or(Event.event_type == 'payment_failed').label('failed'),
            func.min(Event.event_timestamp).label('first_at'),
            func.max(Event.event_timestamp).label('last_at'),
            func.min(Event.event_timestamp).filter(Event.event_type == 'payment_processed').label('processed_at'),
            func.min(Event.event_timestamp).filter(Event.event_type == 'settled').label('settled_at'),
        ).where(Event.transaction_id == transaction_id)
        return self.session.execute(statement).mappings().one()

    def history(self, transaction_id: UUID):
        statement = select(Event.event_id, Event.event_type, Event.event_timestamp,
                           Event.received_at, Event.payload).where(Event.transaction_id == transaction_id)
        return self.session.execute(statement.order_by(Event.event_timestamp, Event.event_id)).mappings().all()
