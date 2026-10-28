# Run the API demo in Postman

1. Import `collection.json` and `render.environment.json` from this folder.
2. Select **Setu — Render** as the active environment.
3. Open the public [health endpoint](https://setu-payment-reconciliation-xn99.onrender.com/health) first. Allow around one minute or longer if the free service is waking up.
4. Run **Setu Payment Reconciliation — API Demo** in order, one iteration.
5. Check the results: the verified run passed 26 requests and 57 assertions.

Each run generates fresh IDs and adds four demo transactions and eight events.
Expected 409/404/422 responses test error handling; they are not failed assertions.
For individual requests, send **Health and initialize demo variables** first,
then follow collection order. Use **Retry identical settlement** to test retries.

For a local Python server, import `local.environment.json` and select **Setu — Local**.
For Docker, set `base_url` to `http://localhost:8001`.

Optional command-line run (Newman installed):

```sh
newman run postman/collection.json -e postman/render.environment.json --bail
```
