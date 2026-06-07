# ShopOS — Demo Walkthrough

End-to-end demo flow. ~10 minutes.

## Setup (once)

```bash
cd "project-ot"
cp .env.example .env
docker compose up -d
# wait ~60s for Postgres + Metabase to be healthy
docker compose exec backend python scripts/seed_demo_data.py
```

## 1. Single source of truth

```
Open  http://localhost:8000/docs
```

Show the OpenAPI explorer — every ingestion endpoint, every admin operation,
typed and documented.

## 2. Manager dashboard

```
Open  http://localhost:3000
```

First boot — set admin email/password.

Connect database:
- Type: PostgreSQL
- Host: `postgres`
- Port: `5432`
- DB: `project_ot`
- User: `ot_admin`
- Password: `changeme_local_only`

Wait ~30s for sync. Then **Browse → ShopOS → public_safe schema**.
You should see six views:

- `daily_revenue`
- `live_payment_matching`
- `shift_summary`
- `inventory_loss_view`
- `employee_accountability`
- `store_health_score`

Build a dashboard for each (or import the JSON exports in `metabase/dashboards/`
once those are saved).

## 3. The planted anomalies

Walk through what the dashboards reveal:

| Anomaly | Where it shows |
|---|---|
| 5 unmatched transfers (last week of data, evening shifts) | `live_payment_matching` — red rows with status `UNMATCHED` |
| 2 cash shortages > 500 THB | `shift_summary` — `cash_discrepancy_thb` column |
| 4 vape carts missing on day 25 | `inventory_loss_view` — `shrinkage_units` for `VP-LIVE-1G` |
| 6 voids by one employee in 30 min | `employee_accountability` — `anomaly_alerts` count |

## 4. Add a deposit manually

Simulate the manager backfilling a missed transfer:

```bash
curl -X POST http://localhost:8000/admin/manual-deposit \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1250.00,
    "bank_timestamp": "2026-05-19T21:13:00+07:00",
    "ref_number": "MANUAL-001",
    "note": "Customer confirmed deposit, SMS missed"
  }'
```

Re-run reconciliation:

```bash
docker compose exec backend python -c "from app.reconciliation.transfers import reconcile_transfers; reconcile_transfers()"
```

The previously-unmatched transfer now flips to VERIFIED in the dashboard.

## 5. Simulate KBank SMS

```bash
docker compose exec backend python scripts/sms_simulator.py
```

Posts two sample KBank SMS to `/ingest/kbank/sms`, signed with HMAC.
You'll see two new rows in `bank_transactions`.

## 6. The audit immutability check

Try to UPDATE the events table:

```bash
docker compose exec postgres psql -U ot_admin -d project_ot \
  -c "UPDATE events SET payload = '{}' WHERE id = 1;"
```

You'll get:

```
ERROR:  events table is append-only — create a correcting event instead
```

This is required for retail audit/tax compliance.

## 7. Owner summary

In a real run this is a daily LINE message at 09:00:

```
STORE HEALTH: 87%

Revenue (last 7d): 312,450 THB
Verified transfers: 142/147
Cash difference: -1,140 THB

Highest-risk shift: Evening, Day 24
Recommended investigation: 2 unmatched transfers + 580 THB cash short
```

Set `LINE_NOTIFY_TOKEN` in `.env` and the scheduled job will post this every morning.

## What this demo does NOT prove yet

- M2: real Loyverse API integration (currently uses synthetic data only)
- M3: real KBank SMS bridge phone (currently uses `sms_simulator.py`)
- M5: cashier PWA for daily stock counts
- M6: full anomaly detection report PDF
- M7: cloud deployment with TLS + Tailscale + encrypted backups
