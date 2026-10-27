"""Explain the actual SQL emitted by read services against the configured database."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.database import get_engine
from app.schemas import TransactionFilters, SummaryFilters, DiscrepancyFilters
from app.services.transactions import list_transactions, get_transaction
from app.services.reconciliation import get_summary, get_discrepancies


def main():
    engine = get_engine()
    with engine.connect() as c:
        counts = dict(
            c.execute(text('''SELECT (SELECT count(*) FROM merchants) AS merchants,
            (SELECT count(*) FROM transactions) AS transactions,
            (SELECT count(*) FROM payment_events) AS events''')).mappings().one()
        )
    captured = []
    current = ''

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            captured.append((current, statement, parameters))

    event.listen(engine, 'before_cursor_execute', capture)
    cases = [
        (
            'merchant_list',
            lambda s: list_transactions(
                s, TransactionFilters(merchant_id='merchant_2')
            ),
        ),
        (
            'status_list',
            lambda s: list_transactions(s, TransactionFilters(status='processed')),
        ),
        (
            'transaction_detail',
            lambda s: get_transaction(s, UUID('6251a96d-9667-4ff2-aa08-cf89e11b1e68')),
        ),
        (
            'merchant_summary',
            lambda s: get_summary(s, SummaryFilters(group_by='merchant')),
        ),
        ('date_summary', lambda s: get_summary(s, SummaryFilters(group_by='date'))),
        ('all_discrepancies', lambda s: get_discrepancies(s, DiscrepancyFilters(), 24)),
        (
            'overdue_discrepancies',
            lambda s: get_discrepancies(
                s, DiscrepancyFilters(reason='overdue_settlement'), 24
            ),
        ),
    ]
    try:
        for current, call in cases:
            with Session(engine) as session:
                call(session)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    rows = []

    def indexes(plan):
        found = [plan['Index Name']] if 'Index Name' in plan else []
        for child in plan.get('Plans', []):
            found += indexes(child)
        return sorted(set(found))

    with engine.connect() as c:
        for name, statement, parameters in captured:
            plan = c.exec_driver_sql(
                'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement, parameters
            ).scalar_one()[0]
            rows.append(
                {
                    'case': name,
                    'execution_ms': plan['Execution Time'],
                    'planning_ms': plan['Planning Time'],
                    'indexes': indexes(plan['Plan']),
                    'plan': plan,
                }
            )
    output = Path('docs')
    output.mkdir(exist_ok=True)
    report = {
        'measured_at': datetime.now(UTC).isoformat(),
        'counts': counts,
        'queries': rows,
    }
    (output / 'performance.json').write_text(json.dumps(report, indent=2))
    lines = [
        '# Local SQL performance check',
        '',
        f'Dataset: {counts}.',
        '',
        'Actual repository queries captured through SQLAlchemy and checked with PostgreSQL EXPLAIN (ANALYZE, BUFFERS).',
        '',
        '| Query | Execution ms | Indexes used |',
        '| --- | ---: | --- |',
    ]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['execution_ms']:.3f} | {', '.join(r['indexes']) or 'Sequential/aggregate plan'} |"
        )
    lines += [
        '',
        'These are individual local measurements on a warm database, not concurrency or production benchmarks.',
        'Reports that aggregate most rows can reasonably use sequential scans. No index is forced.',
        'Each list/report uses two statements (count and page); detail uses transaction and history queries.',
        'Offset pagination and full-dataset report aggregation remain scaling tradeoffs. Re-measure on the hosted database.',
        '',
        'Reproduce from the project root: `python -m scripts.check_performance`. Full plans are in `docs/performance.json`.',
    ]
    (output / 'performance.md').write_text('\n'.join(lines) + '\n')
    print(
        json.dumps(
            {
                'counts': counts,
                'queries_checked': len(rows),
                'slowest_query_ms': max(r['execution_ms'] for r in rows),
            }
        )
    )


if __name__ == '__main__':
    main()
