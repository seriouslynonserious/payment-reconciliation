from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_session, sqlalchemy_url
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app


@pytest.fixture(scope='module')
def db_factory():
    # Unique schema keeps tests isolated from demo data and other test runs.
    url = get_settings().database_url
    schema = 'test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def connect():
        return psycopg.connect(url, autocommit=True, row_factory=dict_row,
                              options=f'-c search_path={schema} -c statement_timeout=10000')
    try:
        with connect() as db:
            db.execute(Path('migrations/001_initial.sql').read_text())
        connect.engine = create_engine(sqlalchemy_url(url), connect_args={
            'options': f'-c search_path={schema} -c timezone=UTC -c statement_timeout=10000',
        })
        yield connect
    finally:
        if hasattr(connect, 'engine'):
            connect.engine.dispose()
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture(scope='module')
def session_factory(db_factory):
    return sessionmaker(db_factory.engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory):
    def override():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


