from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError

from app.repositories.health import HealthRepository
from app.repositories.transactions import TransactionRepository


@pytest.mark.parametrize('error,status', [
    (OperationalError('SELECT 1', {}, psycopg.OperationalError('unavailable')), 503),
    (TimeoutError('Pool exhausted'), 503),
    (IntegrityError('SELECT 1', {}, psycopg.IntegrityError('constraint failure')), 500),
])
def test_sqlalchemy_errors_preserve_public_responses(client, monkeypatch, error, status):
    def fail(self):
        raise error
    monkeypatch.setattr(HealthRepository, 'check', fail)
    response = client.get('/health')
    assert response.status_code == status
    assert 'SELECT' not in response.text
    assert 'constraint failure' not in response.text


def test_failure_after_event_flush_rolls_back_everything(client, db_factory, monkeypatch):
    def fail(self, transaction_id, values):
        raise OperationalError('UPDATE transactions', {}, psycopg.errors.QueryCanceled('timeout'))
    monkeypatch.setattr(TransactionRepository, 'update_state', fail)
    merchant_id = 'rollback_' + uuid4().hex
    transaction_id, event_id = str(uuid4()), str(uuid4())
    response = client.post('/events', json={
        'event_id': event_id, 'transaction_id': transaction_id,
        'merchant_id': merchant_id, 'merchant_name': 'Rollback check',
        'event_type': 'payment_processed', 'amount': '5.00', 'currency': 'INR',
        'timestamp': '2026-01-01T00:00:00Z',
    })
    assert response.status_code == 503
    with db_factory() as db:
        assert db.execute('SELECT * FROM merchants WHERE merchant_id=%s', (merchant_id,)).fetchone() is None
        assert db.execute('SELECT * FROM transactions WHERE transaction_id=%s', (transaction_id,)).fetchone() is None
        assert db.execute('SELECT * FROM payment_events WHERE event_id=%s', (event_id,)).fetchone() is None
