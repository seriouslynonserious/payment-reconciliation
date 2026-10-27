-- Run with psql -v ON_ERROR_STOP=1 -f tests/schema_checks.sql.
-- All fixture rows are rolled back.
BEGIN;
INSERT INTO merchants (merchant_id, merchant_name) VALUES ('schema_check', 'Schema Check');
INSERT INTO transactions (transaction_id, merchant_id, amount, currency, payment_status,
 settlement_status, first_event_at, last_event_at, settled_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'schema_check', 500.10, 'INR',
 'failed', 'settled', now(), now(), now());
INSERT INTO payment_events (event_id, transaction_id, event_type, event_timestamp, payload)
VALUES ('00000000-0000-0000-0000-000000000002',
 '00000000-0000-0000-0000-000000000001', 'settled', now(), '{}');
DO $$
BEGIN
    BEGIN
        INSERT INTO payment_events SELECT * FROM payment_events
        WHERE event_id = '00000000-0000-0000-0000-000000000002';
        RAISE EXCEPTION 'Duplicate event unexpectedly accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO payment_events (event_id, transaction_id, event_type, event_timestamp, payload)
        VALUES ('00000000-0000-0000-0000-000000000003',
          '00000000-0000-0000-0000-000000000099', 'settled', now(), '{}');
        RAISE EXCEPTION 'Orphan event unexpectedly accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE transactions SET merchant_id = 'missing_schema_check'
        WHERE transaction_id = '00000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'Missing merchant unexpectedly accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE transactions SET amount = -1
        WHERE transaction_id = '00000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'Negative amount unexpectedly accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    RAISE NOTICE 'PASS: duplicate IDs, both foreign keys, negative amounts; failed-plus-settled preserved';
END $$;
ROLLBACK;
