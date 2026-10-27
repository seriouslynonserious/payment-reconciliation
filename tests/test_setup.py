import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app.database import sqlalchemy_url
from app.config import get_settings
from scripts.migrate import migrate
from scripts.load_sample_data import load_events


@pytest.fixture
def fresh_engine():
    base = create_engine(sqlalchemy_url(get_settings().database_url))
    schema = 'setup_test_' + uuid4().hex
    with base.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA {schema}')
    engine = create_engine(sqlalchemy_url(get_settings().database_url),
        connect_args={'options': f'-c search_path={schema} -c timezone=UTC'})
    try:
        yield engine
    finally:
        engine.dispose()
        with base.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        base.dispose()


def test_migration_repeatable_and_loader_idempotent(fresh_engine, tmp_path):
    assert migrate(fresh_engine) == ['001_initial.sql']
    assert migrate(fresh_engine) == []
    event = {'event_id':str(uuid4()), 'transaction_id':str(uuid4()), 'merchant_id':'setup_merchant',
        'merchant_name':'Setup Shop', 'amount':'5.00', 'currency':'INR',
        'event_type':'payment_processed', 'timestamp':'2026-01-01T00:00:00Z'}
    path = tmp_path/'events.json';path.write_text(json.dumps([event,event]))
    assert load_events(fresh_engine,path,once=True) == {'submitted':2,'created':1,'duplicates':1,'skipped':False}
    assert load_events(fresh_engine,path,once=True)['skipped'] is True
    assert load_events(fresh_engine,path)['duplicates'] == 2
    with fresh_engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM payment_events')).scalar() == 1


def test_unversioned_tables_not_overwritten(fresh_engine):
    with fresh_engine.begin() as c:
        c.execute(text('CREATE TABLE merchants (id integer)'))
    with pytest.raises(RuntimeError, match='Unversioned'):
        migrate(fresh_engine)


def test_invalid_data_validated_before_writes(fresh_engine,tmp_path):
    migrate(fresh_engine)
    path=tmp_path/'events.json';path.write_text('[{"amount":-1}]')
    with pytest.raises(ValueError):
        load_events(fresh_engine,path)
    with fresh_engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM payment_events')).scalar()==0
