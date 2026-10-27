from concurrent.futures import ThreadPoolExecutor
from itertools import permutations
from datetime import datetime
from uuid import uuid4

import pytest



def event(**changes):
    return dict(dict(event_id=str(uuid4()), transaction_id=str(uuid4()),
                     event_type='payment_initiated', merchant_id='test_merchant',
                     merchant_name='Test Merchant', amount='500.10', currency='INR',
                     timestamp='2026-01-08T12:00:00Z'), **changes)


def test_duplicate_and_changed_payload(client, db_factory):
    body = event()
    assert client.post('/events', json=body).status_code == 201
    equivalent = dict(body, amount=500.1, timestamp='2026-01-08T17:30:00+05:30')
    response = client.post('/events', json=equivalent)
    assert response.status_code == 200
    assert response.json()['duplicate'] is True
    assert client.post('/events', json=dict(body, amount='600')).status_code == 409
    with db_factory() as db:
        assert db.execute('SELECT count(*) AS n FROM payment_events WHERE event_id=%s',
                          (body['event_id'],)).fetchone()['n'] == 1


@pytest.mark.parametrize('order', list(permutations([
    'payment_initiated', 'payment_processed', 'settled',
])))
def test_arrival_order_independence(client, db_factory, order):
    tx = str(uuid4())
    timestamps = dict(payment_initiated='2026-01-08T12:00:00Z',
                      payment_processed='2026-01-08T13:00:00Z', settled='2026-01-08T14:00:00Z')
    for kind in order:
        response = client.post('/events', json=event(transaction_id=tx, event_type=kind,
                                                     timestamp=timestamps[kind]))
        assert response.status_code == 201
    assert response.json()['payment_status'] == 'processed'
    assert response.json()['settlement_status'] == 'settled'
    with db_factory() as db:
        row = db.execute('SELECT * FROM transactions WHERE transaction_id=%s', (tx,)).fetchone()
        assert row['first_event_at'] == datetime.fromisoformat(timestamps['payment_initiated'])
        assert row['processed_at'] == datetime.fromisoformat(timestamps['payment_processed'])
        assert row['settled_at'] == datetime.fromisoformat(timestamps['settled'])


def test_failed_settlement_and_conflicting_payment(client):
    tx = str(uuid4())
    for kind in ['payment_failed', 'settled']:
        response = client.post('/events', json=event(transaction_id=tx, event_type=kind))
        assert response.status_code == 201
    assert response.json()['payment_status'] == 'failed'
    assert response.json()['settlement_status'] == 'settled'
    response = client.post('/events', json=event(transaction_id=tx, event_type='payment_processed'))
    assert response.json()['payment_status'] == 'conflict'


def test_identity_conflict_rolls_back_merchant_and_event(client, db_factory):
    body = event()
    assert client.post('/events', json=body).status_code == 201
    conflicting = event(transaction_id=body['transaction_id'], merchant_id='rollback_merchant')
    assert client.post('/events', json=conflicting).status_code == 409
    with db_factory() as db:
        assert db.execute("SELECT * FROM merchants WHERE merchant_id='rollback_merchant'").fetchone() is None
        assert db.execute('SELECT * FROM payment_events WHERE event_id=%s',
                          (conflicting['event_id'],)).fetchone() is None


@pytest.mark.parametrize('changes', [
    {'amount': '-1'}, {'amount': '1.001'}, {'merchant_id': ' '},
    {'event_type': 'invalid'}, {'timestamp': '2026-01-01T12:00:00'},
    {'currency': 'inr'}, {'event_id': 'invalid'}, {'unexpected': True},
])
def test_validation(client, changes):
    assert client.post('/events', json=event(**changes)).status_code == 422


def test_concurrent_duplicate_submission(client, db_factory):
    body = event()
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(lambda _: client.post('/events', json=body), range(8)))
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]


def test_concurrent_different_events_same_transaction(client, db_factory):
    tx = str(uuid4())
    events = [event(transaction_id=tx, event_type=k) for k in
              ['payment_initiated', 'payment_processed', 'payment_failed', 'settled']]
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda e: client.post('/events', json=e), events))
    assert all(r.status_code == 201 for r in responses)
    with db_factory() as db:
        state = db.execute('SELECT payment_status, settlement_status FROM transactions '
                           'WHERE transaction_id=%s', (tx,)).fetchone()
        assert state == {'payment_status': 'conflict', 'settlement_status': 'settled'}


def test_same_id_different_transactions_concurrently(client, db_factory):
    first = event()
    second = event(event_id=first['event_id'])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda e: client.post('/events', json=e), [first, second]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    with db_factory() as db:
        assert db.execute('SELECT count(*) AS n FROM transactions WHERE transaction_id IN (%s,%s)',
                          (first['transaction_id'], second['transaction_id'])).fetchone()['n'] == 1


def test_health_and_documentation(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/docs').status_code == 200
    assert '/events' in client.get('/openapi.json').json()['paths']
