"""Apply versioned SQL migrations atomically; never recreate existing tables."""
from hashlib import sha256
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import get_engine

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


def migrate(engine: Engine) -> list[str]:
    applied = []
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('schema_migrations', 0))"))
        tables = set(inspect(connection).get_table_names())
        if 'schema_migrations' not in tables and tables.intersection({'merchants', 'transactions', 'payment_events'}):
            raise RuntimeError('Unversioned application tables already exist. Do not reinitialize this database; use the existing local setup or a fresh deployment database.')
        connection.execute(text('''CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
        for file in sorted(MIGRATIONS.glob('*.sql')):
            source = file.read_text()
            checksum = sha256(source.encode()).hexdigest()
            stored = connection.execute(text('SELECT checksum FROM schema_migrations WHERE version=:v'), {'v': file.name}).scalar_one_or_none()
            if stored is not None:
                if stored != checksum:
                    raise RuntimeError(f'Applied migration changed: {file.name}')
                continue
            # Files support psql execution too; transaction ownership here is the engine.
            statements = '\n'.join(line for line in source.splitlines() if line.strip() not in ('BEGIN;', 'COMMIT;'))
            connection.exec_driver_sql(statements)
            connection.execute(text('INSERT INTO schema_migrations(version, checksum) VALUES (:v,:c)'), {'v':file.name, 'c':checksum})
            applied.append(file.name)
    return applied


if __name__ == '__main__':
    print({'applied': migrate(get_engine())})
