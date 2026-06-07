"""Bootstrap Metabase: create admin, connect Postgres, build 6-tile dashboard.

Run from inside the backend container (httpx already installed):
    docker compose exec -T backend python scripts/setup_metabase.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

MB = "http://metabase:3000"

ADMIN_EMAIL = "admin@projectot.local"
ADMIN_PASSWORD = "demo-password-1"
ADMIN_FIRST = "Johnny"
ADMIN_LAST = "Somali"
SITE_NAME = "ShopOS"

PG_DETAILS = {
    "host": "postgres",
    "port": 5432,
    "dbname": "project_ot",
    "user": "ot_admin",
    "password": "changeme_local_only",
    "ssl": False,
    "schema-filters-type": "inclusion",
    "schema-filters-patterns": "public_safe",
}

VIEWS = [
    ("Store Health Score", "store_health_score", "scalar", "score_pct"),
    ("Today Overview", "daily_revenue", "table", None),
    ("Shift Timeline", "shift_summary", "table", None),
    ("Live Payment Matching", "live_payment_matching", "table", None),
    ("Inventory Loss View", "inventory_loss_view", "table", None),
    ("Employee Accountability", "employee_accountability", "table", None),
]


def _client() -> httpx.Client:
    return httpx.Client(base_url=MB, timeout=60.0)


def get_setup_token(c: httpx.Client) -> str | None:
    r = c.get("/api/session/properties")
    r.raise_for_status()
    data = r.json()
    if data.get("has-user-setup"):
        return None
    return data.get("setup-token")


def run_setup(c: httpx.Client, token: str) -> str:
    payload = {
        "token": token,
        "user": {
            "first_name": ADMIN_FIRST,
            "last_name":  ADMIN_LAST,
            "email":      ADMIN_EMAIL,
            "password":   ADMIN_PASSWORD,
            "site_name":  SITE_NAME,
        },
        "prefs": {"site_name": SITE_NAME, "allow_tracking": False},
        "database": None,
    }
    r = c.post("/api/setup", json=payload)
    r.raise_for_status()
    return r.json().get("id")


def login(c: httpx.Client) -> str:
    r = c.post("/api/session", json={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def auth(session_id: str) -> dict:
    return {"X-Metabase-Session": session_id}


def find_or_create_database(c: httpx.Client, session_id: str) -> int:
    r = c.get("/api/database", headers=auth(session_id))
    r.raise_for_status()
    payload = r.json()
    dbs = payload.get("data", payload) if isinstance(payload, dict) else payload
    for db in dbs:
        if db.get("name") == SITE_NAME:
            return db["id"]
    r = c.post(
        "/api/database",
        json={"engine": "postgres", "name": SITE_NAME, "details": PG_DETAILS, "is_full_sync": True},
        headers=auth(session_id),
    )
    r.raise_for_status()
    return r.json()["id"]


def trigger_sync(c: httpx.Client, session_id: str, db_id: int) -> None:
    c.post(f"/api/database/{db_id}/sync_schema", headers=auth(session_id))
    c.post(f"/api/database/{db_id}/rescan_values", headers=auth(session_id))


def find_tables(c: httpx.Client, session_id: str, db_id: int, view_names: list[str], timeout: int = 180) -> dict[str, int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = c.get(f"/api/database/{db_id}/metadata", headers=auth(session_id))
        if r.status_code == 200:
            tables = r.json().get("tables", [])
            found = {t["name"]: t["id"] for t in tables if t.get("schema") == "public_safe"}
            if all(v in found for v in view_names):
                return found
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for views to sync. Last seen: "
                       f"{[t.get('name') for t in tables]}")


def get_field_id(c: httpx.Client, session_id: str, table_id: int, field_name: str) -> int | None:
    r = c.get(f"/api/table/{table_id}/query_metadata", headers=auth(session_id))
    r.raise_for_status()
    for f in r.json().get("fields", []):
        if f["name"] == field_name:
            return f["id"]
    return None


def create_card(c: httpx.Client, session_id: str, name: str, db_id: int, table_id: int,
                display: str, scalar_field_id: int | None) -> int:
    query: dict = {"source-table": table_id}
    if display == "scalar" and scalar_field_id is not None:
        query["fields"] = [["field", scalar_field_id, None]]
    payload = {
        "name": name,
        "dataset_query": {"type": "query", "database": db_id, "query": query},
        "display": display,
        "visualization_settings": {
            "scalar.field": None,
        } if display != "scalar" else {
            "scalar.field": "score_pct",
        },
    }
    r = c.post("/api/card", json=payload, headers=auth(session_id))
    r.raise_for_status()
    return r.json()["id"]


def create_dashboard(c: httpx.Client, session_id: str, name: str) -> int:
    r = c.get("/api/dashboard", headers=auth(session_id))
    r.raise_for_status()
    payload = r.json()
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    for d in items:
        if d.get("name") == name:
            return d["id"]
    r = c.post(
        "/api/dashboard",
        json={"name": name, "description": "Manager view — store health at a glance"},
        headers=auth(session_id),
    )
    r.raise_for_status()
    return r.json()["id"]


def lay_out_dashboard(c: httpx.Client, session_id: str, dash_id: int, card_ids: list[tuple[str, int]]) -> None:
    """Place cards in a 2-column grid: Health big at top, the rest in pairs below."""
    dashcards = []
    health_name, health_id = card_ids[0]
    dashcards.append({
        "id": -1, "card_id": health_id, "row": 0, "col": 0, "size_x": 24, "size_y": 4,
        "parameter_mappings": [], "visualization_settings": {},
    })
    for i, (name, cid) in enumerate(card_ids[1:]):
        row_base = 4 + (i // 2) * 6
        col = 0 if i % 2 == 0 else 12
        dashcards.append({
            "id": -(i + 2), "card_id": cid, "row": row_base, "col": col,
            "size_x": 12, "size_y": 6,
            "parameter_mappings": [], "visualization_settings": {},
        })
    r = c.put(f"/api/dashboard/{dash_id}", json={"dashcards": dashcards}, headers=auth(session_id))
    r.raise_for_status()


def main():
    with _client() as c:
        token = get_setup_token(c)
        if token:
            print(f"Running first-time setup as {ADMIN_FIRST} {ADMIN_LAST} <{ADMIN_EMAIL}>")
            session_id = run_setup(c, token)
        else:
            print("Admin already exists — logging in")
            session_id = login(c)

        print("Connecting database…")
        db_id = find_or_create_database(c, session_id)
        print(f"  database id = {db_id}")

        print("Triggering schema sync…")
        trigger_sync(c, session_id, db_id)

        print("Waiting for public_safe views to sync (up to 3 min)…")
        view_names = [v[1] for v in VIEWS]
        table_ids = find_tables(c, session_id, db_id, view_names)
        print(f"  found {len(table_ids)} views")

        print("Creating dashboard cards…")
        card_ids: list[tuple[str, int]] = []
        for name, view_name, display, scalar_field in VIEWS:
            tid = table_ids[view_name]
            sfid = get_field_id(c, session_id, tid, scalar_field) if scalar_field else None
            cid = create_card(c, session_id, name, db_id, tid, display, sfid)
            print(f"  ✓ {name}  (card #{cid})")
            card_ids.append((name, cid))

        print("Building dashboard…")
        dash_id = create_dashboard(c, session_id, "ShopOS — Store Health")
        lay_out_dashboard(c, session_id, dash_id, card_ids)

        print()
        print("=" * 60)
        print(f"Dashboard ready: http://localhost:3000/dashboard/{dash_id}")
        print(f"Login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print("=" * 60)


if __name__ == "__main__":
    main()
