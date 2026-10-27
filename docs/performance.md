# Local SQL performance check

Dataset: {'merchants': 8, 'transactions': 3810, 'events': 10183}.

Actual repository queries captured through SQLAlchemy and checked with PostgreSQL EXPLAIN (ANALYZE, BUFFERS).

| Query | Execution ms | Indexes used |
| --- | ---: | --- |
| merchant_list | 0.216 | ix_transactions_merchant_date |
| merchant_list | 0.064 | ix_transactions_merchant_date, merchants_pkey |
| status_list | 0.642 | Sequential/aggregate plan |
| status_list | 0.066 | ix_transactions_date, merchants_pkey |
| transaction_detail | 0.027 | merchants_pkey, transactions_pkey |
| transaction_detail | 0.029 | ix_payment_events_transaction_time |
| merchant_summary | 2.137 | Sequential/aggregate plan |
| merchant_summary | 5.358 | Sequential/aggregate plan |
| date_summary | 2.903 | Sequential/aggregate plan |
| date_summary | 3.547 | Sequential/aggregate plan |
| all_discrepancies | 1.635 | Sequential/aggregate plan |
| all_discrepancies | 0.159 | ix_transactions_date, merchants_pkey |
| overdue_discrepancies | 1.792 | Sequential/aggregate plan |
| overdue_discrepancies | 2.312 | merchants_pkey |

These are individual local measurements on a warm database, not concurrency or production benchmarks.
Reports that aggregate most rows can reasonably use sequential scans. No index is forced.
Each list/report uses two statements (count and page); detail uses transaction and history queries.
Offset pagination and full-dataset report aggregation remain scaling tradeoffs. Re-measure on the hosted database.

Reproduce from the project root: `python -m scripts.check_performance`. Full plans are in `docs/performance.json`.
