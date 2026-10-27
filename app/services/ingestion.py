from sqlalchemy.orm import Session

from app.repositories.events import EventRepository
from app.repositories.merchants import MerchantRepository
from app.repositories.transactions import TransactionRepository
from app.schemas import IngestionResult, PaymentEvent


class EventConflict(Exception):
    """The same ID was sent with different payment details."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def payment_state(history) -> str:
    # Check all accepted events, including events received out of order.
    if history['processed'] and history['failed']:
        return 'conflict'
    if history['processed']:
        return 'processed'
    if history['failed']:
        return 'failed'
    if history['initiated']:
        return 'initiated'
    return 'unknown'


def ingest_event(session: Session, event: PaymentEvent) -> IngestionResult:
    events = EventRepository(session)
    merchants = MerchantRepository(session)
    transactions = TransactionRepository(session)
    payload = event.canonical_payload()

    # Save everything together. An error rolls back all changes.
    with session.begin():
        # 1. Handle retries. The lock prevents simultaneous requests racing.
        events.lock_id(event.event_id)
        existing_event = events.find_by_id(event.event_id)

        if existing_event is not None:
            if existing_event.payload != payload:
                raise EventConflict(
                    'event_id_conflict',
                    'Event ID already exists with different data.',
                )

            transaction = transactions.find_by_id(event.transaction_id)
            return IngestionResult(
                event_id=event.event_id,
                transaction_id=event.transaction_id,
                duplicate=True,
                payment_status=transaction.payment_status,
                settlement_status=transaction.settlement_status,
            )

        # 2. Create missing rows, then lock this transaction while updating it.
        merchants.ensure_exists(event.merchant_id, event.merchant_name)
        transactions.ensure_exists(event)
        transaction = transactions.find_by_id(event.transaction_id, for_update=True)

        # A transaction's merchant, amount, and currency cannot change.
        if (
            transaction.merchant_id != event.merchant_id
            or transaction.amount != event.amount
            or transaction.currency != event.currency
        ):
            raise EventConflict(
                'transaction_identity_conflict',
                'Merchant, amount and currency must match the existing transaction.',
            )

        # 3. Save the event and calculate the state from its full history.
        events.add(event, payload)
        history = events.aggregate_history(event.transaction_id)
        payment_status = payment_state(history)
        settlement_status = 'pending'
        if history['settled_at'] is not None:
            settlement_status = 'settled'

        # 4. Update the single current-state row for this transaction.
        transactions.update_state(
            event.transaction_id,
            {
                'payment_status': payment_status,
                'settlement_status': settlement_status,
                'first_event_at': history['first_at'],
                'last_event_at': history['last_at'],
                'processed_at': history['processed_at'],
                'settled_at': history['settled_at'],
            },
        )

        result = IngestionResult(
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            duplicate=False,
            payment_status=payment_status,
            settlement_status=settlement_status,
        )

    # Leaving session.begin() successfully commits the changes before returning.
    return result
