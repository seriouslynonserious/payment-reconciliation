# Payment reconciliation

## Current stage
Implemented: PostgreSQL schema, `POST /events`, `GET /transactions`,
`GET /transactions/{transaction_id}`, both reconciliation APIs, `/health`,
interactive `/docs`, and PostgreSQL integration tests. The full sample dataset has been loaded and verified locally. The Postman collection is complete and verified. Public deployment remains
to be completed.

## Structure
- `app/routes/`: API endpoints.
- `app/services/`: business rules and transaction boundaries.
- `app/repositories/`: SQLAlchemy database queries; no commits.
- `app/models.py`: ORM mappings for merchants, transactions, and payment events.
- `app/database.py`: pooled engine, per-request sessions, and read snapshots.
- `migrations/001_initial.sql`: initial PostgreSQL schema.
- `tests/`: integration and schema checks.
- `scripts/`: versioned migration, sample loading, startup, and query measurement.
- `data/`: supplied sample events; `postman/`: runnable API collection.
- `Dockerfile`, `compose.yaml`, `render.yaml`: local containers and public hosting setup.

## Database setup
Use PostgreSQL 18. Create a dedicated database, then apply the migration once:

```sh
createdb -h localhost setu_reconciliation
psql -h localhost -d setu_reconciliation -v ON_ERROR_STOP=1 -f migrations/001_initial.sql
```

With Postgres.app, commands are under
`/Applications/Postgres.app/Contents/Versions/latest/bin/` if not on your PATH.
Copy `.env.example` to `.env` and replace YOUR_USER before running the API.
This development URL assumes local authentication; deployment credentials must
be supplied through environment variables and never committed.

## Schema decisions
One merchant has many transactions; one transaction has many events.
Primary keys prevent duplicate IDs; foreign keys prevent orphan records.
Deletion is restricted to preserve history. Money uses exact NUMERIC values,
not floating point. This assignment initially supports two-decimal currencies.
All timestamps are timezone-aware; reporting will use UTC.

Payment and settlement are independent. Unknown payment state supports a
settlement arriving first. Conflicting processed/failed events will produce
`conflict`, while retaining both events. No constraint forbids failed payments
from being settled: that inconsistency must be stored and reported.

Event payloads preserve validated values (normalized decimals and UTC timestamps) for audit and semantic comparison
when the same event ID is retried. A unique event ID alone does not implement
full idempotency: ingestion compares payloads and atomically updates state.
Rejected same-ID/different-payload attempts return 409 and never overwrite the
accepted event. Rejected submissions are not stored as accepted event history.

`first_event_at` / `last_event_at` refer to event occurrence, while `created_at`
/ `received_at` refer to ingestion. The service maintains `updated_at` on new accepted events; exact retries do not change it.
Indexes support merchant/status/date filtering, stable pagination, event history,
and overdue settlement queries. Combined filters can initially use one index
and filter remaining rows; measure queries before adding more indexes.

Implemented overdue-settlement rule: processed but unsettled for over 24 hours.
This is a configurable demo assumption, not a Setu settlement policy.

## AI disclosure
OpenAI Codex assisted with planning, sample-data inspection, SQL schema, event
ingestion implementation, documentation, and integration tests. Expand this
section as implementation progresses.

## Run locally (Python 3.13)

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit DATABASE_URL in .env; apply the database migration above if not done yet.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs to submit events interactively.
`GET /health` checks database connectivity. This is a local development service;
public deployment is still pending.

## Event ingestion

```sh
curl -i http://127.0.0.1:8000/events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"711a8f3f-71a4-44cb-bf21-2d4221909edb","event_type":"payment_initiated","transaction_id":"6251a96d-9667-4ff2-aa08-cf89e11b1e68","merchant_id":"merchant_3","merchant_name":"UrbanEats","amount":"12038.91","currency":"INR","timestamp":"2026-01-08T12:37:13.825942Z"}'
```

- 201: unique event accepted; returns IDs, duplicate=false, payment and settlement statuses.
- 200: identical normalized event already exists; duplicate=true and current transaction state.
- 409: same event ID with different content, or changed transaction merchant/amount/currency.
- 422: invalid fields, unsupported event type, unknown fields, or timezone-less timestamp.
- 503: database unavailable/busy; retry with the same event ID.

A new event ID is a distinct event, even if its type repeats. Multiple processed
or settled events do not multiply the transaction amount. Payment success and
failure together produce `conflict`, retaining both events. Settlement arriving
first produces unknown/settled until payment events arrive. Event timestamps
are aggregated independently of arrival order. We do not infer payment success
from settlement. Merchant names use the first accepted name for that merchant;
subsequent submitted names remain in event payloads.

## Implementation choices
We use SQLAlchemy 2.0 ORM models and repositories, with psycopg 3 as the PostgreSQL
driver. Routes handle HTTP, services apply business rules and own transactions,
and repositories handle database queries. All repositories in a service call
share the same Session. `session.begin()` commits successful work and rolls back
exceptions; repository methods never commit. Event insertion flushes before
history aggregation, but a flush does not commit.

The cached engine has a bounded pool (5 connections plus 5 overflow, 5-second
checkout timeout), stale-connection checks, and database connection/query/lock
timeouts. A fresh Session is scoped to each request. PostgreSQL URLs without an
explicit driver are normalized to `postgresql+psycopg` internally.

Event-ID advisory locks and transaction-row locks still prevent duplicate races
and lost updates. ORM models map the existing tables; SQL migrations remain the
authority for all schema constraints/indexes. Never use `Base.metadata.create_all`
as a replacement for the migration, since mappings intentionally do not duplicate
all schema checks/indexes. No tables or existing data are rebuilt by this refactor.

Lists and reports use SQLAlchemy query expressions, retaining database-side
filtering, aggregation, sorting and pagination. Read services use read-only
repeatable-read snapshots; ingestion uses the default read-committed isolation.
SQLAlchemy restores connection isolation/read-only settings before returning
connections to the pool. PostgreSQL-specific advisory locking uses one small
parameterized SQL statement inside the event repository.

There is currently no API authentication; add deployment controls before using
real payment data. Only synthetic data should be used for the assignment demo.

## Tests

```sh
python -m pytest -q
```

Tests require the configured PostgreSQL user to create schemas. They create and
remove a uniquely named test schema, leaving public demo tables untouched.
Coverage includes all six arrival orders, semantic retries, concurrent duplicate
requests, concurrent state changes, identity conflicts and rollback, validation,
failed-but-settled records, and health/docs endpoints.

## Transaction list

`GET /transactions` returns `items`, `total`, `page`, `page_size`, and `total_pages`.
Each item includes merchant ID/name, exact amount (JSON string), currency, payment
and settlement states, and transaction timestamps. Filtering, sorting, counting,
and pagination all happen in PostgreSQL.

| Query parameter | Meaning / default |
| --- | --- |
| `merchant_id` | Exact merchant ID; optional |
| `status` | Payment status: unknown, initiated, processed, failed, conflict |
| `settlement_status` | pending or settled; optional |
| `date_from` | Inclusive earliest-event timestamp; timezone required |
| `date_to` | Exclusive earliest-event timestamp; timezone required |
| `page` | 1-based page; default 1, maximum 1,000,000 |
| `page_size` | Default 20, maximum 100 |
| `sort_by` | first_event_at (default), created_at, amount, payment_status |
| `sort_order` | desc (default) or asc |

```sh
curl --get http://127.0.0.1:8000/transactions \
  --data-urlencode 'merchant_id=merchant_3' \
  --data-urlencode 'date_from=2026-01-01T00:00:00Z' \
  --data-urlencode 'date_to=2026-02-01T00:00:00Z' \
  --data-urlencode 'page_size=10'
```

Date filters use event occurrence time, not ingestion time. Date-only values and
naive timestamps are rejected. To include January 31 fully, use February 1 at
00:00 UTC as the exclusive end. The start must be earlier than the end.
`status=settled` is invalid; use `settlement_status=settled` instead.
All timestamps returned by the application use UTC. Payment-status sorting is
alphabetical. UUID is a secondary sort key in the same direction, giving stable
ordering for equal values. No matches returns 200 with an empty items list and
zero total; a page beyond the end returns empty items with the actual total.
Malformed filters return 422. Sort columns are allowlisted and SQL identifiers
are quoted; filter values are parameterized.

Count and page share a read-only repeatable-read snapshot. Offset pagination is
simple for this dataset; concurrent writes between separate page requests may
shift rows, and deep offsets cost more. Cursor pagination is a future improvement.

## Transaction details

`GET /transactions/{transaction_id}` returns the same transaction fields plus
`events`: event ID, type, event timestamp, received timestamp, and normalized
payload. Events are ordered by occurrence time ascending, then UUID for ties.
Retries do not create additional history entries. A read-only repeatable-read
snapshot keeps state and history consistent during concurrent ingestion.

```sh
curl http://127.0.0.1:8000/transactions/6251a96d-9667-4ff2-aa08-cf89e11b1e68
```

Unknown UUID returns 404 with code `transaction_not_found`. Malformed UUID returns
422. Full event history is returned for one transaction, as required; unusually
large histories would warrant separate pagination in a future version.

Transaction integration tests cover combined filters, timezone-aware date bounds,
stable ordering and pagination, numeric amount sorting, empty/out-of-range pages,
unique event history, merchant details, invalid input, SQL-injection strings, and
missing transactions. These run alongside ingestion and reconciliation integration tests.

## Reconciliation summary

`GET /reconciliation/summary?group_by=merchant` aggregates current transaction
state in SQL. Choose one grouping dimension: `merchant` (default), `date` (UTC
calendar date of first event), or `status` (payment status). Currency is always
an additional grouping key, preventing mixed-currency money totals.

Optional filters: `merchant_id`, `date_from` (inclusive), `date_to` (exclusive).
Date filters use the earliest event timestamp and require timezones. Pagination:
`page` defaults to 1 (maximum 1,000,000), `page_size` to 20 (maximum 100). Groups
sort ascending by group value and currency. `total` counts groups, not payments.

Each group contains:
- `group_value`, `merchant_name` (only for merchant grouping), and `currency`.
- `transaction_count`: all matching transactions, including pending/failed ones.
- `processed_count`, `failed_count`, `conflict_count`: current payment states.
- `settled_count`: all transactions with recorded settlement, even inconsistent ones.
- `pending_settlement_count`: processed payments without settlement, including those still within grace.
- `total_amount`: sum of transaction amounts, not a revenue metric.
- `settled_amount`: sum of amounts on settled transactions, including inconsistent ones.

Settlement counts overlap payment counts; do not add them to compute total
transactions. Monetary values are decimal strings. Transactions are counted
once regardless of number of events or retries. This report describes current
state, not state reconstructed at a historical date. The date grouping is a
transaction cohort grouping, not settlement-day cash flow.

## Reconciliation discrepancies

`GET /reconciliation/discrepancies` returns paginated transactions with an array
of machine-readable `reasons`. Multiple reasons never duplicate a transaction.

| Reason | Condition |
| --- | --- |
| `overdue_settlement` | Processed, unsettled, and strictly older than the configured grace period |
| `settled_failed_payment` | Settled with failed payment evidence (failed or conflict state) |
| `conflicting_payment_events` | Both processed and failed events exist |
| `settlement_without_processed_payment` | Settled while payment state remains unknown or initiated |

The final reason can temporarily arise from out-of-order delivery; it means
investigate the currently known state, not proof of lost funds. Exact duplicates
are harmless and are not discrepancies. Same-event-ID/different-payload requests
are rejected with 409, not stored as additional events. Different event IDs
with contradictory payment outcomes are preserved and flagged as conflicts.

Filters/pagination match summary, plus optional `reason`. Fixed ordering is
first event time descending, then UUID descending. An unmatched reason or page
returns an empty list with the correct total. Returned `reasons` includes every
reason for the transaction, even when filtering by one reason.

`SETTLEMENT_GRACE_HOURS` defaults to 24 (valid range 1–8760). Exactly 24 hours is
not overdue; any later instant is. Optional timezone-aware `as_of` sets the
clock used only for aging; otherwise current UTC time is used. It does NOT
reconstruct historical payment/settlement state. The response includes
`evaluated_at` and `settlement_grace_hours` so results are reproducible for an
unchanged database.

```sh
curl 'http://127.0.0.1:8000/reconciliation/summary?group_by=merchant'
curl 'http://127.0.0.1:8000/reconciliation/summary?group_by=date'
curl --get http://127.0.0.1:8000/reconciliation/discrepancies \
  --data-urlencode 'reason=overdue_settlement' \
  --data-urlencode 'as_of=2026-02-01T00:00:00Z'
```

Both report endpoints use read-only repeatable-read snapshots for count/page
consistency. They aggregate/filter/paginate in SQL and join merchants only as
needed. Page totals can shift between requests as new events arrive. Reporting
tests cover exact monetary totals, duplicate immunity, separate currencies,
all grouping dimensions, UTC date boundaries, multiple discrepancy reasons,
the exact grace boundary, configurable grace, pagination, and invalid inputs.

## Sample data source

`data/sample_events.json` is the unmodified Setu assignment dataset from
https://github.com/SetuHQ/hiring-assignments/blob/main/solutions-engineer/sample_events.json.
It contains 10,355 submitted event records, 10,165 distinct event IDs, and 3,800
transactions across five merchants. The 190 repeated event IDs are intentional;
loading this file through the API stores each unique event only once.

Local practice records may exist in addition to this dataset. Loading the sample
does not delete them. Historical sample payments still awaiting settlement are
overdue when evaluated at the current date. A reproducible aging reference can
be supplied via `as_of`; this does not reconstruct historical transaction state.

Full local load verification: all 10,355 submissions completed without errors;
9,179 new events were inserted and 1,176 submissions were recognized as retries
(including previously loaded events). All 3,800 sample transaction states were
checked against event history. The database also retains one earlier practice
transaction/event, giving 3,801 transactions and 10,166 unique events overall.
At the verification clock, reconciliation returned 475 discrepancies: 380
overdue settlements and 95 settled failed payments. List totals, all three
summary groupings, stored payloads, history, and discrepancy reasons matched.

## Postman collection

Import `postman/collection.json` and `postman/local.environment.json`; see
`postman/README.md` for run instructions. The collection covers all five required
APIs and 26 requests, with 57 passing assertions on the local backend. Each run
creates a dedicated demo merchant with four transactions and eight events, so
unfiltered global counts grow while the original dataset remains intact.

## Reading the layers (Spring Boot comparison)

| Python code | Closest Spring concept |
| --- | --- |
| `app/routes/*.py` | REST controllers |
| `app/schemas.py` | Request/response DTOs with validation |
| `app/services/*.py` | Service layer and transactional boundaries |
| `app/repositories/*.py` | Repository database access |
| `app/models.py` | JPA-style entity mappings |
| `app/database.py` | Data source, pooling, and persistence sessions |

For ingestion, read `services/ingestion.py` first. It asks repositories to lock
and find the event, create missing merchant/transaction rows, check transaction
identity, insert the event, aggregate history, and update current state. Payment
state decisions stay in `payment_state()` in the service; SQL aggregation stays
in the event repository. Reporting classification remains a SQL query expression
in its repository so filtering and pagination happen in PostgreSQL.

SQLAlchemy regression checks additionally cover connection failures, pool timeout,
internal database errors, and rollback after an event has been flushed but before
transaction state is saved. Tests use isolated schemas and verify stored results
through independent psycopg queries.

SQLAlchemy refactor validation: 74 automated tests passed, all 26 Postman requests
and 57 assertions passed, and seven live read responses matched the saved
pre-refactor responses exactly. The Postman rerun added four isolated demo
transactions; it did not change existing sample transactions.

## Deployment preparation

See [deployment instructions](docs/DEPLOYMENT.md) for one-command Docker setup and
Render deployment. Startup applies migrations and loads the sample once. Public
hosting is still pending account/repository setup and live URL verification.

Latest automated validation: **77 tests passed**, including migration reruns,
existing-schema protection, and repeatable sample loading.
[Query measurements](docs/performance.md) record 14 real SQL queries against the
loaded local database, with full plans in `docs/performance.json`. These are local
query timings, not a production load benchmark.
