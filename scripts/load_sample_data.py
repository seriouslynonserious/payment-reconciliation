"""Load synthetic events through the same validation and service used by the API."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database import get_engine
from app.schemas import PaymentEvent
from app.services.ingestion import ingest_event

DEFAULT_FILE = Path(__file__).resolve().parents[1] / 'data/sample_events.json'


def load_events(engine: Engine, path: Path, *, once: bool = False, limit: int | None = None) -> dict:
    source = path.read_bytes()
    rows = json.loads(source)
    if not isinstance(rows, list):
        raise ValueError('Expected a JSON array of events')
    if limit is not None:
        if limit < 1:
            raise ValueError('limit must be positive')
        rows = rows[:limit]
    # Fail invalid input before writing anything. Each accepted event is then atomic.
    events = [PaymentEvent.model_validate(row) for row in rows]
    checksum = sha256(source + str(limit).encode()).hexdigest()
    if once:
        with engine.begin() as connection:
            connection.execute(text('''CREATE TABLE IF NOT EXISTS sample_data_loads (
                checksum TEXT PRIMARY KEY, records INTEGER NOT NULL,
                loaded_at TIMESTAMPTZ NOT NULL DEFAULT now())'''))
            if connection.execute(text('SELECT 1 FROM sample_data_loads WHERE checksum=:c'), {'c':checksum}).scalar():
                return {'submitted': 0, 'created': 0, 'duplicates': 0, 'skipped': True}
    result = {'submitted': len(events), 'created': 0, 'duplicates': 0, 'skipped': False}
    with Session(engine, expire_on_commit=False) as session:
        for index, event in enumerate(events, 1):
            response = ingest_event(session, event)
            result['duplicates' if response.duplicate else 'created'] += 1
            if index % 1000 == 0:
                print(f'Loaded {index}/{len(events)} events', flush=True)
    # A failed/partial run is never marked complete; reruns safely retry committed events.
    if once:
        with engine.begin() as connection:
            connection.execute(text('''INSERT INTO sample_data_loads(checksum,records) VALUES (:c,:n)
                ON CONFLICT (checksum) DO NOTHING'''), {'c':checksum, 'n':len(events)})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=Path, default=DEFAULT_FILE)
    parser.add_argument('--once', action='store_true', help='Skip files successfully loaded by this mode before')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    print(json.dumps(load_events(get_engine(), args.file, once=args.once, limit=args.limit)))
