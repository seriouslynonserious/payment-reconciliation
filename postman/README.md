# Postman demo collection

1. In Postman, choose Import and select `collection.json` and `local.environment.json`.
2. Select the `Setu — Local` environment. Its `base_url` is http://127.0.0.1:8000.
3. Open `Setu Payment Reconciliation — API Demo` and run the entire collection in order, one iteration.
4. Check the test results. Validation on the local backend passed all 26 requests and 57 assertions.

Each full run generates new UUIDs and a dedicated `postman_...` merchant, creating
four synthetic transactions and eight unique events. It preserves existing data.
This adds three discrepancies to the overall database totals. Filters in the
collection isolate its demo merchant from the original sample data.

For individual requests, first send `Health and initialize demo variables`, then
send dependent requests in collection order. Repeating a create-event request
returns 200 as an idempotent retry; its original 201 assertion will then fail by
design. Use `Retry identical settlement` to verify the duplicate response. Run
the full collection to start a fresh demonstration with new IDs.

Folders cover health, successful lifecycle, duplicate handling, changed event
payloads, conflicting transaction identity, failed-but-settled payments, overdue
settlements, contradictory payment events, transaction filters/pagination,
transaction history, all three summary groupings, discrepancy reason filters,
and 422 validation errors. The 409/404/422 responses are expected successes in
the test run, not test failures.

The collection assumes the default 24-hour settlement grace period and uses a
fixed aging reference of 2026-01-10T00:00:00Z for reproducibility. Do not override
its generated IDs with environment variables of the same names.

For deployment, duplicate the environment and replace `base_url` with the public
API origin, without a trailing slash. No secrets or credentials are included.

Optional CLI execution (Node.js and Newman required):

```sh
newman run postman/collection.json -e postman/local.environment.json --bail
```

For a public deployment, add `--env-var base_url=https://YOUR-PUBLIC-API`.
