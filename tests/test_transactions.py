from uuid import uuid4

import pytest

from app.schemas import PaymentEvent
from app.services.ingestion import ingest_event


@pytest.fixture(scope='module')
def sample(session_factory):
    merchant = 'list_' + uuid4().hex
    other = 'other_' + uuid4().hex
    ids = [str(uuid4()) for _ in range(4)]
    definitions = [
        (ids[0], merchant, '10.20', '2026-02-01T00:00:00Z', ['payment_initiated', 'payment_processed', 'settled']),
        (ids[1], merchant, '2.00', '2026-02-02T00:00:00Z', ['payment_initiated', 'payment_processed']),
        (ids[2], merchant, '10.20', '2026-02-02T00:00:00Z', ['payment_initiated', 'payment_failed']),
        (ids[3], other, '90.00', '2026-02-03T00:00:00Z', ['settled']),
    ]
    for tx, mid, amount, timestamp, kinds in definitions:
        # Reverse arrival order, retaining equal timestamps to exercise UUID ties.
        for kind in reversed(kinds):
            event = PaymentEvent(event_id=uuid4(), transaction_id=tx, merchant_id=mid,
                merchant_name='List Merchant', amount=amount, currency='INR',
                event_type=kind, timestamp=timestamp)
            with session_factory() as db:
                ingest_event(db, event)
                ingest_event(db, event)  # A retry must never double the history.
    return {'merchant': merchant, 'other': other, 'ids': ids}


def test_combined_filters(client, sample):
    response = client.get('/transactions', params={
        'merchant_id': sample['merchant'], 'status': 'processed',
        'settlement_status': 'pending', 'date_from': '2026-02-02T00:00:00Z',
        'date_to': '2026-02-03T00:00:00Z',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['items'][0]['transaction_id'] == sample['ids'][1]
    assert body['items'][0]['amount'] == '2.00'
    assert body['items'][0]['merchant_name'] == 'List Merchant'
    assert 'events' not in body['items'][0]


def test_date_bounds_and_timezone(client, sample):
    response = client.get('/transactions', params={
        'merchant_id': sample['merchant'], 'date_from': '2026-02-01T05:30:00+05:30',
        'date_to': '2026-02-02T05:30:00+05:30',
    })
    assert response.status_code == 200
    assert [r['transaction_id'] for r in response.json()['items']] == [sample['ids'][0]]


@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_stable_pagination_and_timestamp_ties(client, sample, direction):
    collected = []
    for page in range(1, 4):
        response = client.get('/transactions', params={'merchant_id': sample['merchant'],
            'page_size': 1, 'page': page, 'sort_order': direction})
        assert response.status_code == 200
        body = response.json()
        assert (body['total'], body['total_pages'], body['page']) == (3, 3, page)
        collected.append(body['items'][0]['transaction_id'])
    ascending = [sample['ids'][0], *sorted(sample['ids'][1:3])]
    assert collected == (ascending if direction == 'asc' else ascending[::-1])
    beyond = client.get('/transactions', params={'merchant_id': sample['merchant'],
        'page_size': 1, 'page': 4}).json()
    assert beyond['items'] == []
    assert beyond['total'] == 3


@pytest.mark.parametrize('sort_by', ['amount', 'payment_status', 'created_at'])
@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_other_sort_columns(client, sample, sort_by, direction):
    response = client.get('/transactions', params={'merchant_id': sample['merchant'],
        'sort_by': sort_by, 'sort_order': direction})
    assert response.status_code == 200
    rows = response.json()['items']
    from decimal import Decimal
    values = [(Decimal(r[sort_by]) if sort_by == 'amount' else r[sort_by], r['transaction_id']) for r in rows]
    assert values == sorted(values, reverse=direction == 'desc')


def test_empty_page(client):
    body = client.get('/transactions', params={'merchant_id': 'missing_' + uuid4().hex}).json()
    assert body == {'items': [], 'total': 0, 'page': 1, 'page_size': 20, 'total_pages': 0}


def test_detail_returns_unique_history_and_merchant(client, sample):
    response = client.get('/transactions/' + sample['ids'][0])
    assert response.status_code == 200
    body = response.json()
    assert body['merchant_id'] == sample['merchant']
    assert body['merchant_name'] == 'List Merchant'
    assert body['payment_status'] == 'processed'
    assert body['settlement_status'] == 'settled'
    events = body['events']
    assert len(events) == 3
    assert {e['event_type'] for e in events} == {'payment_initiated', 'payment_processed', 'settled'}
    assert [e['event_id'] for e in events] == sorted(e['event_id'] for e in events)
    assert all(e['payload']['transaction_id'] == sample['ids'][0] for e in events)
    assert all(e['received_at'] for e in events)


def test_detail_unknown_payment_and_missing_transaction(client, sample):
    assert client.get('/transactions/' + sample['ids'][3]).json()['payment_status'] == 'unknown'
    response = client.get('/transactions/' + str(uuid4()))
    assert response.status_code == 404
    assert response.json()['detail']['code'] == 'transaction_not_found'
    assert client.get('/transactions/not-a-uuid').status_code == 422


@pytest.mark.parametrize('params', [
    {'page': 0}, {'page': -1}, {'page_size': 0}, {'page_size': 101},
    {'sort_by': 'amount; DROP TABLE transactions'}, {'sort_order': 'sideways'},
    {'status': 'settled'}, {'settlement_status': 'failed'}, {'merchant_id': ' '},
    {'date_from': '2026-02-01T00:00:00'}, {'date_to': 'bad-date'},
    {'date_from': '2026-02-02T00:00:00Z', 'date_to': '2026-02-01T00:00:00Z'},
    {'date_from': '2026-02-01T00:00:00Z', 'date_to': '2026-02-01T00:00:00Z'},
    {'unknown_filter': 'value'},
])
def test_bad_query_returns_422(client, params):
    assert client.get('/transactions', params=params).status_code == 422


def test_filter_values_are_not_sql(client, sample):
    response = client.get('/transactions', params={'merchant_id': "' OR 1=1 --"})
    assert response.status_code == 200
    assert response.json()['total'] == 0


def test_routes_documented(client):
    paths = client.get('/openapi.json').json()['paths']
    assert '/transactions' in paths
    assert '/transactions/{transaction_id}' in paths
