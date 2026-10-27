from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.config import get_settings


def sqlalchemy_url(database_url: str):
    """Keep existing PostgreSQL URLs compatible while selecting psycopg 3."""
    url = make_url(database_url)
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    return url


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        sqlalchemy_url(get_settings().database_url),
        pool_pre_ping=True, pool_size=5, max_overflow=5, pool_timeout=5,
        connect_args={
            'connect_timeout': 5,
            'options': '-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000',
        },
    )


def get_session() -> Iterator[Session]:
    # One session per request; services own commit/rollback boundaries.
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@contextmanager
def read_transaction(session: Session):
    """Use one consistent snapshot for count/page or details/history."""
    with session.begin():
        session.connection(execution_options={
            'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True,
        })
        yield

