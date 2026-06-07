# Screenshots

The README has a commented-out image slot for the live dashboard. To fill it (~2 minutes):

1. Bring the stack up and seed demo data (from the repo root):
   ```bash
   docker compose up -d
   # wait ~60s for healthchecks
   docker compose exec -e OT_ALLOW_SEED=1 backend python scripts/seed_demo_data.py
   ```
2. Open **http://localhost:8000/dashboard** — the seeder plants anomalies, so the
   store-health score and alerts feed will have content to show.
3. Capture it:
   - **Static PNG** — `Win + Shift + S`, drag over the dashboard, save here as `dashboard.png`.
   - **Animated GIF** (better — shows the alerts feed) — record with [ScreenToGif](https://www.screentogif.com/),
     export as `dashboard.gif`, and point the README line at it instead.
4. In `README.md`, delete the `<!-- -->` around the `![ShopOS dashboard](...)` line.

Keep it reasonably small (< ~2 MB) so the repo stays light.
