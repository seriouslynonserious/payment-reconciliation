from datetime import datetime
from uuid import uuid4

import pytest

from app.config import get_settings
from app.main import app
from app.schemas import PaymentEvent
from app.services.ingestion import ingest_event


@pytest.fixture(scope='module')
def report_data(session_factory):
    merchant = 'report_' + uuid4().hex
    other = 'other_' + uuid4().hex
    definitions = [
        ('success', '100', 'INR', '2026-01-01T00:00:00Z', ['payment_processed', 'settled']),
        ('overdue', '200', 'INR', '2026-01-01T00:00:00Z', ['payment_processed']),
        ('boundary', '300', 'INR', '2026-01-02T00:00:00Z', ['payment_processed']),
        ('recent', '400', 'INR', '2026-01-02T12:00:00Z', ['payment_processed']),
        ('failed_settled', '500', 'INR', '2026-01-01T00:00:00Z', ['payment_failed', 'settled']),
        ('conflict', '600', 'INR', '2026-01-01T00:00:00Z', ['payment_processed', 'payment_failed', 'settled']),
        ('orphan_settlement', '700', 'INR', '2026-01-01T00:00:00Z', ['settled']),
        ('initiated', '800', 'INR', '2026-01-01T00:00:00Z', ['payment_initiated']),
        ('failed', '900', 'INR', '2026-01-01T00:00:00Z', ['payment_failed']),
        ('usd', '50', 'USD', '2026-01-01T00:00:00Z', ['payment_processed', 'settled']),
    ]
    ids = {}
    for name, amount, currency, timestamp, kinds in definitions:
        tx = uuid4()
        ids[name] = str(tx)
        for kind in reversed(kinds):
            event = PaymentEvent(event_id=uuid4(), transaction_id=tx, merchant_id=merchant,
                merchant_name='Report Shop', amount=amount, currency=currency,
                timestamp=timestamp, event_type=kind)
            with session_factory() as db:
                ingest_event(db, event)
                ingest_event(db, event)
    with session_factory() as db:
        ingest_event(db, PaymentEvent(event_id=uuid4(), transaction_id=uuid4(), merchant_id=other,
            merchant_name='Other Shop', amount='1000', currency='INR',
            timestamp='2026-01-01T00:00:00Z', event_type='payment_processed'))
    return {'merchant_id': merchant, 'ids': ids, 'as_of': '2026-01-03T00:00:00Z'}


def test_summary_counts_money_and_currency_separation(client, report_data):
    response = client.get('/reconciliation/summary', params={'merchant_id': report_data['merchant_id']})
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 2
    inr, usd = body['items']
    assert inr == dict(group_value=report_data['merchant_id'], merchant_name='Report Shop', currency='INR',
        transaction_count=9, processed_count=4, failed_count=2, conflict_count=1, settled_count=4,
        pending_settlement_count=3, total_amount='4500.00', settled_amount='1900.00')
    assert usd['transaction_count'] == 1
    assert usd['currency'] == 'USD'
    assert usd['total_amount'] == '50.00'


def test_summary_group_by_date_utc_and_filters(client, report_data):
    response = client.get('/reconciliation/summary', params={
        'merchant_id': report_data['merchant_id'], 'group_by': 'date',
        'date_from': '2026-01-02T05:30:00+05:30', 'date_to': '2026-01-03T00:00:00Z',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['items'][0]['group_value'] == '2026-01-02'
    assert body['items'][0]['transaction_count'] == 2
    assert body['items'][0]['total_amount'] == '700.00'
    assert body['items'][0]['merchant_name'] is None


def test_summary_group_by_status(client, report_data):
    body = client.get('/reconciliation/summary', params={
        'merchant_id': report_data['merchant_id'], 'group_by': 'status',
    }).json()
    groups = {(r['group_value'], r['currency']): r for r in body['items']}
    assert body['total'] == 6
    assert groups['processed', 'INR']['transaction_count'] == 4
    assert groups['processed', 'USD']['transaction_count'] == 1
    assert groups['conflict', 'INR']['transaction_count'] == 1
    assert groups['unknown', 'INR']['settled_count'] == 1


def test_discrepancies_reasons_and_grace_boundary(client, report_data):
    response = client.get('/reconciliation/discrepancies', params={
        'merchant_id': report_data['merchant_id'], 'as_of': report_data['as_of'],
    })
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 4
    assert body['settlement_grace_hours'] == 24
    assert datetime.fromisoformat(body['evaluated_at']) == datetime.fromisoformat(report_data['as_of'])
    reasons = {r['transaction_id']: r['reasons'] for r in body['items']}
    ids = report_data['ids']
    assert reasons == {
        ids['overdue']: ['overdue_settlement'],
        ids['failed_settled']: ['settled_failed_payment'],
        ids['conflict']: ['settled_failed_payment', 'conflicting_payment_events'],
        ids['orphan_settlement']: ['settlement_without_processed_payment'],
    }
    response = client.get('/reconciliation/discrepancies', params={
        'merchant_id': report_data['merchant_id'], 'as_of': '2026-01-03T00:00:00.000001Z',
        'reason': 'overdue_settlement',
    })
    assert response.json()['total'] == 2


def test_reason_filter_returns_all_reasons_and_single_transaction(client, report_data):
    body = client.get('/reconciliation/discrepancies', params={
        'merchant_id': report_data['merchant_id'], 'reason': 'conflicting_payment_events',
        'as_of': report_data['as_of'],
    }).json()
    assert body['total'] == 1
    assert len(body['items'][0]['reasons']) == 2


def test_grace_setting_and_clock_offsets(client, report_data):
    settings = get_settings().model_copy(update={'settlement_grace_hours': 48})
    app.dependency_overrides[get_settings] = lambda: settings
    body = client.get('/reconciliation/discrepancies', params={
        'merchant_id': report_data['merchant_id'], 'as_of': '2026-01-03T05:30:00+05:30',
    }).json()
    assert body['total'] == 3
    assert body['settlement_grace_hours'] == 48


@pytest.mark.parametrize('endpoint,expected', [('summary', 2), ('discrepancies', 4)])
def test_report_pagination(client, report_data, endpoint, expected):
    params = {'merchant_id': report_data['merchant_id'], 'page_size': 1}
    if endpoint == 'discrepancies':
        params['as_of'] = report_data['as_of']
    items = []
    for page in range(1, expected + 1):
        body = client.get('/reconciliation/' + endpoint, params=dict(params, page=page)).json()
        assert body['total'] == expected
        assert body['total_pages'] == expected
        items += body['items']
    key = 'currency' if endpoint == 'summary' else 'transaction_id'
    assert len({r[key] for r in items}) == expected
    body = client.get('/reconciliation/' + endpoint, params=dict(params, page=99)).json()
    assert body['items'] == []
    assert body['total'] == expected


@pytest.mark.parametrize('endpoint', ['summary', 'discrepancies'])
def test_empty_report(client, endpoint):
    body = client.get('/reconciliation/' + endpoint, params={'merchant_id': "' OR 1=1 --"}).json()
    assert body['items'] == []
    assert body['total'] == 0


@pytest.mark.parametrize('endpoint,params', [
    ('summary', {'group_by': 'currency; DROP TABLE transactions'}),
    ('summary', {'page_size': 101}), ('summary', {'page': 0}),
    ('summary', {'date_from': '2026-02-01T00:00:00Z', 'date_to': '2026-01-01T00:00:00Z'}),
    ('summary', {'date_from': '2026-01-01T00:00:00'}),
    ('discrepancies', {'as_of': '2026-01-01T00:00:00'}),
    ('discrepancies', {'reason': 'duplicate'}),
    ('discrepancies', {'page_size': 0}), ('discrepancies', {'merchant_id': ' '}),
])
def test_invalid_report_filters(client, endpoint, params):
    assert client.get('/reconciliation/' + endpoint, params=params).status_code == 422


def test_default_clock_and_routes(client):
    response = client.get('/reconciliation/discrepancies')
    assert response.status_code == 200
    assert response.json()['evaluated_at']
    paths = client.get('/openapi.json').json()['paths']
    assert '/reconciliation/summary' in paths
    assert '/reconciliation/discrepancies' in paths
