"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("SET TIME ZONE 'Asia/Bangkok';")

    op.execute(
        """
        CREATE TABLE events (
            id              BIGSERIAL PRIMARY KEY,
            source          VARCHAR(64)  NOT NULL,
            event_type      VARCHAR(128) NOT NULL,
            payload         JSONB        NOT NULL,
            received_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            source_timestamp TIMESTAMPTZ,
            source_id       VARCHAR(256),
            idempotency_key VARCHAR(256) NOT NULL UNIQUE,
            corrects_event_id BIGINT REFERENCES events(id)
        );
        CREATE INDEX idx_events_source_time ON events(source, source_timestamp);
        CREATE INDEX idx_events_received   ON events(received_at);

        -- Audit immutability (retail audit/tax compliance)
        CREATE OR REPLACE FUNCTION prevent_event_modification() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'events table is append-only — create a correcting event instead';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER no_update_events BEFORE UPDATE ON events
            FOR EACH ROW EXECUTE FUNCTION prevent_event_modification();
        CREATE TRIGGER no_delete_events BEFORE DELETE ON events
            FOR EACH ROW EXECUTE FUNCTION prevent_event_modification();
        """
    )

    op.execute(
        """
        CREATE TABLE employees (
            id                   SERIAL PRIMARY KEY,
            name                 VARCHAR(128) NOT NULL,
            loyverse_employee_id VARCHAR(64) UNIQUE,
            neocall_id           VARCHAR(64) UNIQUE,
            active               BOOLEAN NOT NULL DEFAULT TRUE,
            role                 VARCHAR(64) NOT NULL DEFAULT 'cashier'
        );

        CREATE TABLE shifts (
            id                    SERIAL PRIMARY KEY,
            scheduled_start       TIMESTAMPTZ NOT NULL,
            scheduled_end         TIMESTAMPTZ NOT NULL,
            actual_start          TIMESTAMPTZ,
            actual_end            TIMESTAMPTZ,
            employee_ids          INT[] NOT NULL,
            attendance_confidence NUMERIC(3,2) DEFAULT 1.0,
            status                VARCHAR(32) NOT NULL DEFAULT 'scheduled'
        );
        CREATE INDEX idx_shifts_time ON shifts(scheduled_start, scheduled_end);

        CREATE TABLE attendance_logs (
            id                    BIGSERIAL PRIMARY KEY,
            employee_id           INT NOT NULL REFERENCES employees(id),
            fingerprint_timestamp TIMESTAMPTZ NOT NULL,
            event_type            VARCHAR(32) NOT NULL,
            raw_event_id          BIGINT REFERENCES events(id)
        );
        CREATE INDEX idx_attendance_emp_time ON attendance_logs(employee_id, fingerprint_timestamp);
        """
    )

    op.execute(
        """
        CREATE TABLE pos_transactions (
            receipt_id      VARCHAR(128) PRIMARY KEY,
            timestamp       TIMESTAMPTZ NOT NULL,
            total           NUMERIC(12,2) NOT NULL,
            cash_amount     NUMERIC(12,2) NOT NULL DEFAULT 0,
            transfer_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            payment_method  VARCHAR(32)  NOT NULL,
            employee_id     INT REFERENCES employees(id),
            shift_id        INT REFERENCES shifts(id),
            void_status     VARCHAR(16)  NOT NULL DEFAULT 'active',
            refund_of_id    VARCHAR(128),
            discount_amount NUMERIC(12,2) DEFAULT 0,
            line_items      JSONB NOT NULL,
            raw_event_id    BIGINT REFERENCES events(id)
        );
        CREATE INDEX idx_pos_time     ON pos_transactions(timestamp);
        CREATE INDEX idx_pos_shift    ON pos_transactions(shift_id);
        CREATE INDEX idx_pos_employee ON pos_transactions(employee_id);
        CREATE INDEX idx_pos_method   ON pos_transactions(payment_method);

        CREATE TABLE bank_transactions (
            id              BIGSERIAL PRIMARY KEY,
            bank_timestamp  TIMESTAMPTZ NOT NULL,
            amount          NUMERIC(12,2) NOT NULL,
            direction       VARCHAR(8)  NOT NULL,
            sender          VARCHAR(64),
            ref_number      VARCHAR(64),
            balance         NUMERIC(12,2),
            raw_sms         TEXT,
            idempotency_key VARCHAR(256) NOT NULL UNIQUE,
            raw_event_id    BIGINT REFERENCES events(id)
        );
        CREATE INDEX idx_bank_time   ON bank_transactions(bank_timestamp);
        CREATE INDEX idx_bank_amount ON bank_transactions(amount);

        CREATE TABLE transfer_matches (
            id                  BIGSERIAL PRIMARY KEY,
            pos_transaction_id  VARCHAR(128) NOT NULL UNIQUE REFERENCES pos_transactions(receipt_id),
            bank_transaction_id BIGINT REFERENCES bank_transactions(id),
            status              VARCHAR(32) NOT NULL,
            confidence          NUMERIC(3,2),
            time_delta_seconds  INT,
            matched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_matches_status ON transfer_matches(status);
        """
    )

    op.execute(
        """
        CREATE TABLE inventory_items (
            sku              VARCHAR(64) PRIMARY KEY,
            name             VARCHAR(256) NOT NULL,
            category         VARCHAR(64),
            unit             VARCHAR(16) NOT NULL DEFAULT 'piece',
            loyverse_item_id VARCHAR(64) UNIQUE,
            active           BOOLEAN NOT NULL DEFAULT TRUE,
            cost_thb         NUMERIC(12,2),
            price_thb        NUMERIC(12,2)
        );

        CREATE TABLE inventory_movements (
            id            BIGSERIAL PRIMARY KEY,
            timestamp     TIMESTAMPTZ NOT NULL,
            sku           VARCHAR(64) NOT NULL REFERENCES inventory_items(sku),
            movement_type VARCHAR(32) NOT NULL,
            quantity      NUMERIC(12,3) NOT NULL,
            reference_id  VARCHAR(128),
            shift_id      INT REFERENCES shifts(id),
            raw_event_id  BIGINT REFERENCES events(id)
        );
        CREATE INDEX idx_inv_mov_sku_time ON inventory_movements(sku, timestamp);

        CREATE TABLE inventory_counts (
            id              BIGSERIAL PRIMARY KEY,
            shift_id        INT NOT NULL REFERENCES shifts(id),
            sku             VARCHAR(64) NOT NULL REFERENCES inventory_items(sku),
            count_type      VARCHAR(16) NOT NULL,
            counted_value_1 NUMERIC(12,3) NOT NULL,
            counted_value_2 NUMERIC(12,3) NOT NULL,
            final_value     NUMERIC(12,3) NOT NULL,
            counted_by      INT REFERENCES employees(id),
            counted_at      TIMESTAMPTZ NOT NULL,
            UNIQUE(shift_id, sku, count_type)
        );

        CREATE TABLE shift_sales_reports (
            id                BIGSERIAL PRIMARY KEY,
            shift_id          INT NOT NULL REFERENCES shifts(id),
            employee_id       INT NOT NULL REFERENCES employees(id),
            sku               VARCHAR(64) NOT NULL REFERENCES inventory_items(sku),
            reported_quantity NUMERIC(12,3) NOT NULL,
            reported_at       TIMESTAMPTZ NOT NULL,
            notes             TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE cash_sessions (
            id              SERIAL PRIMARY KEY,
            shift_id        INT NOT NULL UNIQUE REFERENCES shifts(id),
            opening_amount  NUMERIC(12,2) NOT NULL,
            expected_close  NUMERIC(12,2),
            counted_close_1 NUMERIC(12,2),
            counted_close_2 NUMERIC(12,2),
            final_count     NUMERIC(12,2),
            discrepancy     NUMERIC(12,2),
            status          VARCHAR(32) NOT NULL DEFAULT 'open',
            opened_at       TIMESTAMPTZ NOT NULL,
            closed_at       TIMESTAMPTZ
        );

        CREATE TABLE alerts (
            id                   BIGSERIAL PRIMARY KEY,
            severity             VARCHAR(16) NOT NULL,
            alert_type           VARCHAR(64) NOT NULL,
            payload              JSONB NOT NULL,
            financial_impact_thb NUMERIC(12,2),
            shift_id             INT REFERENCES shifts(id),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at         TIMESTAMPTZ,
            acked_at             TIMESTAMPTZ,
            acked_by             INT REFERENCES employees(id),
            line_message_id      VARCHAR(128)
        );
        CREATE INDEX idx_alerts_unacked ON alerts(severity, created_at) WHERE acked_at IS NULL;

        CREATE TABLE discrepancies (
            id                BIGSERIAL PRIMARY KEY,
            discrepancy_type  VARCHAR(64) NOT NULL,
            shift_id          INT REFERENCES shifts(id),
            employee_id       INT REFERENCES employees(id),
            sku               VARCHAR(64),
            expected          NUMERIC(12,2),
            actual            NUMERIC(12,2),
            delta             NUMERIC(12,2),
            detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved          BOOLEAN NOT NULL DEFAULT FALSE,
            resolution_notes  TEXT
        );
        CREATE INDEX idx_discrepancies_type_time ON discrepancies(discrepancy_type, detected_at);

        CREATE TABLE sms_bridge_heartbeats (
            id           SERIAL PRIMARY KEY,
            received_at  TIMESTAMPTZ NOT NULL,
            bridge_id    VARCHAR(64) NOT NULL,
            battery_pct  INT,
            network_type VARCHAR(16)
        );
        CREATE INDEX idx_sms_heartbeat_time ON sms_bridge_heartbeats(received_at);
        """
    )

    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS public_safe;
        GRANT USAGE ON SCHEMA public_safe TO PUBLIC;

        -- All views live under public_safe so Metabase only sees aggregated, PII-free data.
        CREATE OR REPLACE VIEW public_safe.daily_revenue AS
        SELECT
            (timestamp AT TIME ZONE 'Asia/Bangkok')::date AS business_day,
            COUNT(*)                                              AS receipt_count,
            SUM(total)                                            AS total_thb,
            SUM(cash_amount)                                      AS cash_thb,
            SUM(transfer_amount)                                  AS transfer_thb,
            SUM(discount_amount)                                  AS discount_thb,
            COUNT(*) FILTER (WHERE void_status = 'voided')        AS voids,
            COUNT(*) FILTER (WHERE void_status = 'refunded')      AS refunds
        FROM pos_transactions
        GROUP BY 1
        ORDER BY 1 DESC;

        CREATE OR REPLACE VIEW public_safe.live_payment_matching AS
        SELECT
            p.receipt_id,
            p.timestamp,
            p.total,
            p.transfer_amount,
            p.payment_method,
            tm.status,
            tm.confidence,
            tm.time_delta_seconds,
            b.bank_timestamp,
            b.ref_number
        FROM pos_transactions p
        LEFT JOIN transfer_matches tm ON tm.pos_transaction_id = p.receipt_id
        LEFT JOIN bank_transactions b ON b.id = tm.bank_transaction_id
        WHERE p.payment_method IN ('transfer', 'mixed')
        ORDER BY p.timestamp DESC;

        CREATE OR REPLACE VIEW public_safe.shift_summary AS
        SELECT
            s.id AS shift_id,
            s.scheduled_start,
            s.scheduled_end,
            s.actual_start,
            s.actual_end,
            s.status,
            array_to_string(
                ARRAY(SELECT e.name FROM employees e WHERE e.id = ANY(s.employee_ids)),
                ', '
            ) AS employees,
            COALESCE(SUM(p.total), 0)           AS revenue_thb,
            COUNT(p.receipt_id)                 AS receipt_count,
            cs.discrepancy                      AS cash_discrepancy_thb,
            (SELECT COUNT(*) FROM discrepancies d WHERE d.shift_id = s.id) AS discrepancy_count
        FROM shifts s
        LEFT JOIN pos_transactions p ON p.shift_id = s.id
        LEFT JOIN cash_sessions cs ON cs.shift_id = s.id
        GROUP BY s.id, cs.discrepancy
        ORDER BY s.scheduled_start DESC;

        CREATE OR REPLACE VIEW public_safe.inventory_loss_view AS
        SELECT
            i.sku,
            i.name,
            i.category,
            COALESCE(mv.received, 0) AS received,
            COALESCE(mv.sold, 0)     AS sold,
            COALESCE(mv.damaged, 0)  AS damaged,
            COALESCE(mv.adjusted, 0) AS adjusted,
            COALESCE(dq.shrinkage_units, 0)  AS shrinkage_units,
            COALESCE(dq.shrinkage_events, 0) AS shrinkage_events
        FROM inventory_items i
        LEFT JOIN LATERAL (
            SELECT
                SUM(quantity) FILTER (WHERE movement_type = 'received') AS received,
                SUM(quantity) FILTER (WHERE movement_type = 'sold')     AS sold,
                SUM(quantity) FILTER (WHERE movement_type = 'damaged')  AS damaged,
                SUM(quantity) FILTER (WHERE movement_type = 'adjusted') AS adjusted
            FROM inventory_movements WHERE sku = i.sku
        ) mv ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                SUM(delta) AS shrinkage_units,
                COUNT(*)   AS shrinkage_events
            FROM discrepancies
            WHERE sku = i.sku AND discrepancy_type = 'INVENTORY_SHRINKAGE'
        ) dq ON TRUE
        WHERE i.active = TRUE
        ORDER BY shrinkage_units DESC NULLS LAST;

        CREATE OR REPLACE VIEW public_safe.employee_accountability AS
        SELECT
            e.id AS employee_id,
            e.name,
            COALESCE(p.transactions_handled, 0) AS transactions_handled,
            COALESCE(s.shifts_worked, 0)        AS shifts_worked,
            COALESCE(d.open_discrepancies, 0)   AS open_discrepancies,
            COALESCE(d.total_impact_thb, 0)     AS total_impact_thb,
            COALESCE(a.anomaly_alerts, 0)       AS anomaly_alerts
        FROM employees e
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS transactions_handled
            FROM pos_transactions WHERE employee_id = e.id
        ) p ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS shifts_worked
            FROM shifts WHERE e.id = ANY(employee_ids)
        ) s ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE resolved = FALSE) AS open_discrepancies,
                SUM(delta) AS total_impact_thb
            FROM discrepancies WHERE employee_id = e.id
        ) d ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS anomaly_alerts
            FROM alerts
            WHERE severity IN ('WARN','CRITICAL')
              AND shift_id IN (SELECT id FROM shifts WHERE e.id = ANY(employee_ids))
        ) a ON TRUE
        WHERE e.active = TRUE
        ORDER BY total_impact_thb DESC NULLS LAST;

        CREATE OR REPLACE VIEW public_safe.store_health_score AS
        WITH today AS (
            SELECT CURRENT_DATE AS d
        ),
        match_rate AS (
            SELECT
                COUNT(*) FILTER (WHERE tm.status = 'VERIFIED')::numeric
                / NULLIF(COUNT(*), 0)::numeric AS rate
            FROM transfer_matches tm
            JOIN pos_transactions p ON p.receipt_id = tm.pos_transaction_id
            WHERE (p.timestamp AT TIME ZONE 'Asia/Bangkok')::date >= (SELECT d - 7 FROM today)
        ),
        cash_ok AS (
            SELECT
                1 - LEAST(1, COALESCE(SUM(ABS(discrepancy)) / NULLIF(SUM(opening_amount), 0), 0))
                    AS rate
            FROM cash_sessions
            WHERE closed_at >= NOW() - INTERVAL '7 days'
        ),
        unresolved AS (
            SELECT COUNT(*) AS n
            FROM discrepancies
            WHERE resolved = FALSE AND detected_at >= NOW() - INTERVAL '7 days'
        )
        SELECT
            ROUND(
                100 * (
                    COALESCE((SELECT rate FROM match_rate), 1) * 0.4 +
                    COALESCE((SELECT rate FROM cash_ok), 1)   * 0.3 +
                    GREATEST(0, 1 - (SELECT n FROM unresolved)::numeric / 20) * 0.3
                )
            )::int AS score_pct,
            CASE
                WHEN (SELECT n FROM unresolved) > 10 THEN 'red'
                WHEN COALESCE((SELECT rate FROM match_rate), 1) < 0.9 THEN 'yellow'
                ELSE 'green'
            END AS status_color,
            (SELECT n FROM unresolved) AS open_discrepancies;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sms_bridge_heartbeats CASCADE;")
    op.execute("DROP TABLE IF EXISTS discrepancies CASCADE;")
    op.execute("DROP TABLE IF EXISTS alerts CASCADE;")
    op.execute("DROP TABLE IF EXISTS cash_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS shift_sales_reports CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory_counts CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory_movements CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS transfer_matches CASCADE;")
    op.execute("DROP TABLE IF EXISTS bank_transactions CASCADE;")
    op.execute("DROP TABLE IF EXISTS pos_transactions CASCADE;")
    op.execute("DROP TABLE IF EXISTS attendance_logs CASCADE;")
    op.execute("DROP TABLE IF EXISTS shifts CASCADE;")
    op.execute("DROP TABLE IF EXISTS employees CASCADE;")
    op.execute("DROP TRIGGER IF EXISTS no_delete_events ON events;")
    op.execute("DROP TRIGGER IF EXISTS no_update_events ON events;")
    op.execute("DROP FUNCTION IF EXISTS prevent_event_modification();")
    op.execute("DROP TABLE IF EXISTS events CASCADE;")
