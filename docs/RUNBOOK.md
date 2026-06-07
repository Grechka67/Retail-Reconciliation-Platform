# ShopOS — Runbook

Day-to-day operational guide.

## Daily checklist (manager, 10 sec)

1. Open Metabase → check Store Health Score (top of Today Overview)
2. Scan Live Payment Matching for any red/yellow status
3. Review Open Alerts in n8n inbox or LINE group

## Starting and stopping the stack

```bash
docker compose up -d        # start everything in background
docker compose ps           # see what's running
docker compose logs -f      # tail all logs
docker compose down         # stop (preserves data)
docker compose down -v      # stop and DELETE all data (do not run carelessly)
```

## Re-seeding the demo

```bash
docker compose exec -e OT_ALLOW_SEED=1 backend python scripts/seed_demo_data.py
```

It **truncates every table first**, then loads 30 days of fresh synthetic data. The
`OT_ALLOW_SEED=1` flag is a guard so this can never wipe a real database by accident — never run it
against live store data.

## When the SMS bridge goes silent

You'll get a CRITICAL alert via LINE: "KBank SMS bridge offline".

1. Check the bridge phone is on and connected to Wi-Fi
2. Open the SMS Forwarder app — is it running? Restart if needed
3. Check phone clock matches Bangkok time (drift breaks reconciliation)
4. In the meantime, enter deposits manually via `POST /admin/manual-deposit`
   (or the admin UI when built)

## Backups

Nightly backup script (runs from host cron, not Docker):

```bash
scripts/backup.sh
```

Encrypts a `pg_dump` of `project_ot` with age, uploads to Backblaze B2.
**Verify a restore at least once per month.**

## Adding a new dashboard question in Metabase

1. Open http://localhost:3000
2. New → Question → Native query OR GUI builder
3. Use a `public_safe.*` view — never query the underlying tables directly
   (PII redaction lives in the views)
4. Save to the appropriate dashboard

## Restoring from a backup

```bash
docker compose down
docker volume rm project-ot_postgres_data
docker compose up -d postgres
age -d -i ~/.age/key backup_2026-05-19.sql.age | docker compose exec -T postgres psql -U ot_admin -d project_ot
docker compose up -d
```

## Common issues

**Metabase shows no data**
Check Postgres connection: Admin → Databases → Test connection. The host is `postgres`, port `5432`, db `project_ot`, user `ot_admin`.

**`alembic upgrade head` fails on first boot**
The DB may not be ready. `docker compose logs postgres` — wait for "ready to accept connections" then `docker compose restart backend`.

**Transfer matches all UNMATCHED**
Likely clock drift. Check `SELECT NOW();` on Postgres vs the bridge phone time. Both must be `Asia/Bangkok`.

**Append-only events trigger blocking my UPDATE**
By design. Create a new event with `corrects_event_id` pointing to the bad one. Never bypass the trigger — retail audit/tax compliance requires audit immutability.
