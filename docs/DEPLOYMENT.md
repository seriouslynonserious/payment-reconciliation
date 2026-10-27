# Deployment and reviewer setup

## Run with Docker

Install and open Docker Desktop, then run from the project directory:

```sh
docker compose up --build -d
docker compose logs -f api
```

First startup creates the schema and loads the supplied sample through the same
validation and ingestion service as the API. Wait for Uvicorn to report startup
complete. Open http://localhost:8001/docs and http://localhost:8001/health.
The database uses its own persistent Docker volume. Stop with `docker compose down`;
the data is retained. This does not use the existing local PostgreSQL database.

The fresh sample contains 10,355 submissions, 10,165 unique events, 3,800
transactions, and five merchants. Successful loading is recorded by file checksum;
restarts skip the completed file. Partial loads resume safely using event IDs.

## Public deployment on Render

1. Create or sign into https://dashboard.render.com/ using GitHub.
2. Publish this project to a GitHub repository, excluding `.env` and `.venv`.
3. Select **New → Blueprint**, connect the repository, and select `render.yaml`.
4. Review the two free services: API and PostgreSQL in Singapore. Apply the Blueprint.
5. Wait for database creation, Docker build, schema migration, and sample loading.
6. Open the assigned API URL followed by `/health`, then `/docs`.
7. Set Postman's `base_url` to that HTTPS URL (without a trailing slash) and run the collection.
8. Add the verified public URL to the submission and README.

`DATABASE_URL` comes from Render's database connection reference. Do not commit
credentials. `LOAD_SAMPLE_DATA=true` loads synthetic assignment data on first
startup. `SETTLEMENT_GRACE_HOURS=24` controls overdue classification.
The database blocks external connections; the API connects over Render's network.

Render's free web service sleeps after 15 minutes without inbound traffic and
can take about a minute to wake. Free PostgreSQL expires after 30 days. Ensure the
database remains available through the review period; choose a paid plan yourself
if a longer lifetime is required. See https://render.com/docs/free.

## Migration behavior

`scripts/start.sh` runs versioned migrations before starting the server. Migration
checksums prevent silently changing an already applied migration. Use a fresh
database for Docker/Render. The migration runner deliberately refuses an existing
unversioned schema; the earlier manually initialized development database should
continue using the README's direct Uvicorn command.

## Demo checks

- `/health`: database connection works.
- `/transactions`: one current row per transaction, with pagination.
- `/transactions/{transaction_id}`: current state and retained event history.
- `/reconciliation/summary?group_by=merchant`: counts and amounts by merchant/currency.
- `/reconciliation/discrepancies`: inconsistent transactions with explicit reasons.
- Run the Postman collection to check ingestion, exact retries, conflicts, filters,
  and validation. It adds isolated synthetic demo records.

No public deployment URL has been verified yet. The API is an unauthenticated
assignment demo containing synthetic data; production authentication is outside
this implementation.
