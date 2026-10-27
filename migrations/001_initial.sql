-- Run once against a dedicated empty PostgreSQL database.
BEGIN;

CREATE TABLE merchants (
    merchant_id TEXT PRIMARY KEY CHECK (length(trim(merchant_id)) > 0),
    merchant_name TEXT NOT NULL CHECK (length(trim(merchant_name)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id) ON DELETE RESTRICT,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    payment_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (payment_status IN ('unknown', 'initiated', 'processed', 'failed', 'conflict')),
    settlement_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (settlement_status IN ('pending', 'settled')),
    first_event_at TIMESTAMPTZ NOT NULL,
    last_event_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (last_event_at >= first_event_at),
    CHECK ((settlement_status = 'settled') = (settled_at IS NOT NULL))
);

CREATE TABLE payment_events (
    event_id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES transactions(transaction_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'payment_initiated', 'payment_processed', 'payment_failed', 'settled'
    )),
    event_timestamp TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX ix_transactions_merchant_date
    ON transactions (merchant_id, first_event_at DESC, transaction_id DESC);
CREATE INDEX ix_transactions_status_date
    ON transactions (payment_status, first_event_at DESC, transaction_id DESC);
CREATE INDEX ix_transactions_date
    ON transactions (first_event_at DESC, transaction_id DESC);
CREATE INDEX ix_transactions_pending_settlement
    ON transactions (processed_at)
    WHERE payment_status = 'processed' AND settlement_status = 'pending';
CREATE INDEX ix_payment_events_transaction_time
    ON payment_events (transaction_id, event_timestamp, event_id);

COMMIT;
