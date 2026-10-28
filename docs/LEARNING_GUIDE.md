# Understanding this project

Read in this order: schemas → routes → services → repositories → database/models.
The project keeps the same controller/service/repository structure used in Spring.
AI assisted with this implementation; use this guide to understand and explain the
actual choices, and keep that assistance disclosure in the submission.

## 1. Python syntax used here

| Syntax | Meaning / Java comparison |
| --- | --- |
| `from x import y` | Import a name from another module (file/package). |
| `def name(...):` | Define a function. Indentation replaces Java braces. |
| `value: str` / `-> str` | Input/return type hints. Python itself does not enforce them; Pydantic validates model fields. |
| `class X(Base):` | Define a class inheriting from Base. |
| `self` | Current object, like Java `this`; explicitly written in method parameters. |
| `__init__` | Constructor used to initialize an object. |
| `None` / `True` / `False` | Java null / true / false. JSON uses null / true / false. |
| `str`, `int`, `bool`, `dict`, `list` | String, integer, boolean, map, list. |
| `UUID`, `Decimal`, `datetime` | Typed identifiers, exact money, timestamps. |
| `X \| None` | Either X or None. |
| `Literal['a', 'b']` | Allowed values, similar to an enum for validation. |
| `@...` | Decorator: registers or modifies a class/function. Similar uses to annotations, but executable Python. |
| `with ...:` | Enter and leave a managed scope, similar to try-with-resources. |
| `raise Error(...)` | Throw an exception. |
| `yield session` | Supply the session temporarily, then resume cleanup afterward. |
| `**row` | Expand a dictionary into named arguments: `{'amount': 10}` becomes `amount=10`. |
| `*columns` | Expand a sequence into separate arguments to a function. |
| `//` | Integer division; used to calculate page counts. |
| `f'ID: {value}'` | Insert a value into a string. |
| `async def` | Coroutine function. Our exception handlers use this; synchronous database routes use normal `def`. |

## 2. What each file does

### app/config.py — application properties

- `Settings(BaseSettings)` reads environment variables, or local `.env` values.
- `database_url` is required; it contains connection information.
- `Field(default=24, ge=1, le=8760)` sets the grace period and validates its range.
- `@lru_cache` reuses settings instead of reading configuration for every request.

### app/database.py — DataSource and sessions

- `sqlalchemy_url()` selects the psycopg PostgreSQL driver, including for Render URLs.
- `get_engine()` creates a reusable connection pool. Five normal and five extra connections are allowed.
- `pool_pre_ping=True` checks reused connections; timeouts prevent waiting indefinitely.
- `get_session()` opens one session per request, yields it, then closes it.
- `expire_on_commit=False` keeps loaded attributes usable after commit.
- `read_transaction()` gives related reads one consistent snapshot. For example,
  the count and page should describe the same database state within that request.
- A session is like a persistence context, not the database itself.

### app/models.py — JPA-style entities

- `Base(DeclarativeBase)` provides SQLAlchemy's mapping machinery.
- `__tablename__` identifies the actual PostgreSQL table.
- `Mapped[...]` describes a Python attribute stored in the database.
- `mapped_column(...)` supplies column type, primary key, foreign key, or default.
- `Merchant` stores merchant identity and name.
- `Transaction` stores ONE current state per transaction ID.
- `PaymentEventRecord` stores each accepted event and its normalized JSON payload.
- `Numeric(18, 2)` stores exact monetary values. JSONB stores structured JSON.
- SQL migrations create tables and enforce the full constraints; these mappings
  do not create the schema by themselves.

### app/schemas.py — DTOs and validation

- `PaymentEvent` validates incoming JSON. UUIDs must be valid, amount positive,
  currency three uppercase letters, and timestamp timezone-aware.
- `extra='forbid'` rejects unknown fields; `str_strip_whitespace` trims strings.
- `normalize_timestamp()` converts event times to UTC.
- `canonical_payload()` produces normalized JSON; amounts such as 10 and 10.00
  compare equally when checking retries.
- `IngestionResult` defines the POST response, including whether it was a duplicate.
- `TransactionFilters` defines pagination, sorting, merchant/status/date filters.
- `validate_date_range()` rejects reversed/equal date boundaries.
- `TransactionSummary` describes a list item; `TransactionDetail` adds event history.
- `EventHistoryItem` describes one accepted historical event.
- `TransactionPage` packages items with pagination information.
- `ReconciliationFilters` contains shared report filters; `SummaryFilters` adds grouping.
- `SummaryGroup` describes counts and exact totals for one group/currency.
- `ReconciliationSummary` wraps summary groups and pagination.
- `DiscrepancyFilters` adds reason and aging-clock filters.
- `DiscrepancyReason` restricts reason names; `DiscrepancyItem` adds reasons to a transaction.
- `DiscrepancyPage` adds the evaluation time and grace period to its paginated response.

### app/routes/*.py — REST controllers

- `APIRouter` groups related endpoints. `@router.get` and `@router.post` register URLs.
- `Annotated[Session, Depends(get_session)]` asks FastAPI to provide a database session.
- `Annotated[...Filters, Query()]` reads filters from the URL query parameters.
- `response_model` validates and describes the response in Swagger.
- `events.py`: calls ingestion; returns 201 for new events, 200 for exact retries.
- `transactions.py`: lists current states, or gets one transaction; missing IDs return 404.
- `reconciliation.py`: calls the summary/discrepancy services and supplies the grace period.
- Routes translate HTTP inputs/outputs; repositories perform SQL work.

### app/services/ingestion.py — accepting a payment event

Read `ingest_event()` from top to bottom:

1. Create repositories sharing the same session; normalize the request payload.
2. `with session.begin()` starts a database transaction. Success commits; errors roll back.
3. Lock the event ID so simultaneous retries do not both get treated as new.
4. If the ID exists, compare payloads. Different payload → conflict; same payload →
   return the transaction's current state with `duplicate=True` and no new writes.
5. Create the merchant and transaction only if missing.
6. Lock the transaction row so two new events cannot overwrite each other's calculations.
7. Check that merchant, amount, and currency match the original transaction.
8. Insert the event and flush it, making it visible to our own following query.
9. Aggregate the full accepted history and calculate payment/settlement states.
10. Update the transaction's single current-state row and prepare the response.
11. Commit when the `with` block exits successfully, then return the response.

`payment_state()` gives conflict priority when processed AND failed events exist.
Otherwise processed wins, then failed, then initiated, or unknown if only settlement
exists. This supports events arriving out of order; arrival order is not lifecycle order.
`EventConflict` carries a short error code and a human-readable message.

### app/services/transactions.py and reconciliation.py — reading results

- `list_transactions()` asks the repository for a count/page and builds the response.
- `get_transaction()` fetches current state and history in the same read snapshot.
- `get_summary()` obtains grouped counts/amounts and adds pagination.
- `get_discrepancies()` chooses UTC now or `as_of`, then obtains flagged transactions.
- `(total + page_size - 1) // page_size` rounds up: 21 rows at size 20 means 2 pages.
- `as_of` only controls aging; it does not recreate an old database snapshot.

### app/repositories/*.py — database queries

A common sequence is now written as separate steps:

```python
statement = select(Transaction).where(Transaction.transaction_id == transaction_id)
result = self.session.execute(statement)
return result.scalar_one()
```

1. Build a SQL statement; no query has run yet.
2. Execute it using the request's session.
3. Read the returned object.

`mappings()` returns named columns like dictionaries; `all()` returns all selected
rows; `one()` requires exactly one row; `one_or_none()` permits no row.
`scalar_one()` extracts one value/object and requires exactly one row.

- **merchants.py:** `ensure_exists()` uses INSERT ON CONFLICT DO NOTHING.
- **events.py:** `lock_id()` takes a PostgreSQL transaction-scoped advisory lock;
  `find_by_id()` looks up a primary key; `add()` inserts and flushes an event;
  `aggregate_history()` finds which event types exist and earliest/latest times;
  `history()` returns accepted events in timestamp/ID order.
- **transactions.py:** `ensure_exists()` inserts a missing transaction; `find_by_id()`
  optionally locks it with FOR UPDATE; `populate_existing=True` refreshes cached
  attributes after waiting for a concurrent writer; `update_state()` updates the row;
  `find_details()` joins the merchant; `list_page()` filters, counts, sorts, and pages.
- `SORT_COLUMNS` allows only known sort columns. The transaction ID breaks sort ties.
- **reconciliation.py:** `report_conditions()` builds shared filters. `summary_page()`
  groups by merchant/date/status AND currency so INR and USD are never added together.
  `discrepancy_page()` builds reason conditions, excludes unflagged rows, then pages.
- `func.count/sum/min/max/bool_or` calls SQL functions, not Python calculations.
- `case()` is SQL CASE; `and_()` combines SQL conditions; `cte()` names an intermediate
  SQL result. `array_remove(..., None)` removes missing reasons; `any_()` checks membership.
- **health.py:** performs a database check for `/health`.
- Repositories do not commit: the service controls the whole operation's transaction.

### Reconciliation rules in plain language

| Reason | Meaning |
| --- | --- |
| overdue_settlement | Processed, still pending, and strictly older than the grace period. |
| settled_failed_payment | Settled even though payment is failed or conflicting. |
| conflicting_payment_events | Both processed and failed events were accepted. |
| settlement_without_processed_payment | Settled while payment is unknown or merely initiated. |

A failed payment alone is not a discrepancy. One transaction can have multiple reasons.
A pending count is not necessarily the same as the discrepancy count: filters, aging,
and additional inconsistency types matter.

### app/main.py — application entry point

- Creates FastAPI and attaches the routers.
- Maps `EventConflict` to HTTP 409.
- Unwraps SQLAlchemy driver errors: temporary connection/pool/query-cancellation
  problems return 503; other database errors return a generic 500.
- Logs diagnostic details on the server, without returning them to clients.
- Exposes `/health` for Render and basic connection checks.

### Migration, scripts, tests, and deployment

- `migrations/001_initial.sql`: primary keys, foreign keys, checks, timestamps,
  and indexes. Do not edit it after application; add another migration instead.
- `scripts/migrate.py`: locks migration execution, records version/checksum,
  skips already applied files, and refuses an unversioned existing schema.
- `scripts/load_sample_data.py`: validates the sample, ingests each event using
  the same service, counts new/duplicate events, and records successful completion.
- `scripts/start.sh`: migrates, starts the API, imports sample data, then waits
  for the server. If loading fails, it stops the server. First import is gradual.
- `scripts/check_performance.py`: records actual SQL plans/timings; optional diagnostic tool.
- `tests/conftest.py`: creates isolated test schemas; tests do not clear demo tables.
- `test_events.py`: duplicates, conflicts, ordering and transaction state.
- `test_transactions.py`: list/detail, filters, sorting and pagination.
- `test_reconciliation.py`: counts, money, currencies, aging and inconsistency reasons.
- `test_sqlalchemy_errors.py`: error responses and transaction rollback.
- `test_setup.py`: migration safety and repeatable sample loading.
- `schema_checks.sql`: database constraint checks.
- `postman/`: collection and local/Render environment URLs for API checks.
- `Dockerfile`: packages Python, dependencies, source and startup command.
- `compose.yaml`: local API and PostgreSQL containers with persistent database storage.
- `render.yaml`: declares the hosted API/database and environment configuration.
- `requirements.txt`: pinned Python dependencies; `.env.example`: configuration template.
- `.gitignore` / `.dockerignore`: exclude local/generated files from Git/build context.
- Empty `__init__.py` files identify packages; `.gitkeep` files are directory placeholders.

## 3. A short explanation you can practice

“The API accepts payment events and validates them with Pydantic. A service checks
retries and transaction identity, saves the event, and recalculates current state
inside one database transaction. SQLAlchemy repositories handle queries. We keep
all accepted events for history and one current row for each transaction. Reporting
queries aggregate totals and flag inconsistencies. PostgreSQL stores the data, and
Render runs the API and database. AI assisted with the code; I am learning and can
walk through the implementation.”

## 4. Small learning exercises

1. Trace a processed event followed by settlement: why is there still only one transaction?
2. Predict the response when the exact same event is sent twice. Then test it in Swagger.
3. Explain why `flush()` must happen before the history query but does not commit.
4. Use page size 2 and explain how page 3 gets offset 4.
5. Explain why an ordinary failed payment is excluded from discrepancy results.
6. Find the line that returns 404 for a missing transaction.
