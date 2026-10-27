from sqlalchemy.orm import Session

from app.repositories.events import EventRepository
from app.repositories.merchants import MerchantRepository
from app.repositories.transactions import TransactionRepository
from app.schemas import IngestionResult, PaymentEvent


class EventConflict(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def payment_state(history) -> str:
    """Business rules use facts aggregated by the event repository."""
    if history['processed'] and history['failed']:
        return 'conflict'
    if history['processed']:
        return 'processed'
    if history['failed']:
        return 'failed'
    return 'initiated' if history['initiated'] else 'unknown'


def ingest_event(session: Session, event: PaymentEvent) -> IngestionResult:
    events = EventRepository(session)
    merchants = MerchantRepository(session)
    transactions = TransactionRepository(session)
    payload = event.canonical_payload()

    # All repositories share this session and one atomic database transaction.
    with session.begin():
        events.lock_id(event.event_id)
        existing = events.find_by_id(event.event_id)
        if existing is not None:
            if existing.payload != payload:
                raise EventConflict('event_id_conflict', 'Event ID already exists with different data.')
            transaction = transactions.find_by_id(event.transaction_id)
            return IngestionResult(event_id=event.event_id, transaction_id=event.transaction_id,
                duplicate=True, payment_status=transaction.payment_status,
                settlement_status=transaction.settlement_status)

        merchants.ensure_exists(event.merchant_id, event.merchant_name)
        transactions.ensure_exists(event)
        transaction = transactions.find_by_id(event.transaction_id, for_update=True)
        if (transaction.merchant_id, transaction.amount, transaction.currency) != (
            event.merchant_id, event.amount, event.currency,
        ):
            raise EventConflict('transaction_identity_conflict',
                'Merchant, amount and currency must match the existing transaction.')

        events.add(event, payload)
        history = events.aggregate_history(event.transaction_id)
        status = payment_state(history)
        settlement = 'settled' if history['settled_at'] is not None else 'pending'
        transactions.update_state(event.transaction_id, {
            'payment_status': status, 'settlement_status': settlement,
            'first_event_at': history['first_at'], 'last_event_at': history['last_at'],
            'processed_at': history['processed_at'], 'settled_at': history['settled_at'],
        })
        result = IngestionResult(event_id=event.event_id, transaction_id=event.transaction_id,
            duplicate=False, payment_status=status, settlement_status=settlement)
    return result
