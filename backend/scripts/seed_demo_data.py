"""Seed 30 days of synthetic store data with planted anomalies.

Run inside the backend container:
    docker compose exec backend python scripts/seed_demo_data.py

Planted anomalies (so the demo dashboards have something to show):
    - 5 unmatched transfers   → UNMATCHED_TRANSFER alerts
    - 2 cash shortages > 500  → CASH_DISCREPANCY alerts
    - 1 inventory shrinkage   → INVENTORY_SHRINKAGE alerts
    - 1 void burst by an employee
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import random
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db import engine, session_scope
from app.models import (
    Alert,
    AttendanceLog,
    BankTransaction,
    CashSession,
    Discrepancy,
    Employee,
    Event,
    InventoryItem,
    InventoryMovement,
    PosTransaction,
    Shift,
    SmsBridgeHeartbeat,
)
from app.reconciliation.transfers import reconcile_transfers

BKK = ZoneInfo("Asia/Bangkok")
RNG = random.Random(20260519)


EMPLOYEES = [
    {"name": "Ploy",     "role": "manager",   "neocall_id": "FP-001"},
    {"name": "Nong",     "role": "cashier", "neocall_id": "FP-002"},
    {"name": "Beam",     "role": "cashier", "neocall_id": "FP-003"},
    {"name": "Mai",      "role": "cashier", "neocall_id": "FP-004"},
    {"name": "Tar",      "role": "cashier", "neocall_id": "FP-005"},
]

CATALOGUE = [
    # Beverages
    {"sku": "BV-COLA",    "name": "Cola 500ml",               "category": "beverage", "unit": "bottle", "price": 50,   "cost": 18},
    {"sku": "BV-WATER",   "name": "Water 600ml",              "category": "beverage", "unit": "bottle", "price": 20,   "cost": 7},
    {"sku": "BV-ICED",    "name": "Iced Tea 480ml",           "category": "beverage", "unit": "bottle", "price": 40,   "cost": 14},
    {"sku": "BV-COFFEE",  "name": "Canned Coffee",            "category": "beverage", "unit": "can",    "price": 35,   "cost": 13},
    {"sku": "BV-ENERGY",  "name": "Energy Drink",             "category": "beverage", "unit": "bottle", "price": 15,   "cost": 6},
    # Snacks
    {"sku": "SN-CHIPS",   "name": "Potato Chips",             "category": "snack",    "unit": "pack",   "price": 30,   "cost": 12},
    {"sku": "SN-NUTS",    "name": "Roasted Nuts",             "category": "snack",    "unit": "pack",   "price": 45,   "cost": 20},
    {"sku": "SN-CHOC",    "name": "Chocolate Bar",            "category": "snack",    "unit": "piece",  "price": 35,   "cost": 15},
    {"sku": "SN-COOKIE",  "name": "Cookies",                  "category": "snack",    "unit": "pack",   "price": 25,   "cost": 10},
    # Household
    {"sku": "HH-DETERG",  "name": "Laundry Detergent",        "category": "household","unit": "pack",   "price": 120,  "cost": 70},
    {"sku": "HH-TISSUE",  "name": "Tissue Box",               "category": "household","unit": "box",    "price": 45,   "cost": 22},
    {"sku": "HH-SOAP",    "name": "Dish Soap",                "category": "household","unit": "bottle", "price": 60,   "cost": 30},
    # Personal care
    {"sku": "PC-SHAMP",   "name": "Shampoo Sachet",           "category": "personal", "unit": "piece",  "price": 10,   "cost": 4},
    {"sku": "PC-TOOTH",   "name": "Toothpaste",               "category": "personal", "unit": "tube",   "price": 55,   "cost": 25},
    {"sku": "PC-MASK",    "name": "Face Mask 5-pack",         "category": "personal", "unit": "pack",   "price": 40,   "cost": 18},
    # General
    {"sku": "GN-BATT",    "name": "AA Batteries 4-pack",      "category": "general",  "unit": "pack",   "price": 80,   "cost": 40},
    {"sku": "GN-LIGHT",   "name": "Lighter",                  "category": "general",  "unit": "piece",  "price": 30,   "cost": 8},
    {"sku": "GN-UMBR",    "name": "Umbrella",                 "category": "general",  "unit": "piece",  "price": 150,  "cost": 70},
]


def _idem(*parts) -> str:
    return sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _truncate_all(conn):
    """Wipe data tables in dependency order so we can re-seed cleanly."""
    conn.execute(text("""
        TRUNCATE TABLE
            transfer_matches,
            inventory_counts,
            shift_sales_reports,
            inventory_movements,
            attendance_logs,
            cash_sessions,
            discrepancies,
            alerts,
            pos_transactions,
            bank_transactions,
            sms_bridge_heartbeats
        RESTART IDENTITY CASCADE;
    """))
    # Events use a no-update trigger but TRUNCATE bypasses row triggers
    conn.execute(text("TRUNCATE TABLE events RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE shifts RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE inventory_items CASCADE;"))
    conn.execute(text("TRUNCATE TABLE employees RESTART IDENTITY CASCADE;"))


def main():
    # Safety guard: this TRUNCATEs every table. Never let it run against real data.
    if os.environ.get("OT_ALLOW_SEED") != "1":
        print(
            "Refusing to seed: this script TRUNCATES every table (total data loss).\n"
            "Only run it against a throwaway/demo database. To confirm, re-run with:\n"
            "    OT_ALLOW_SEED=1 python scripts/seed_demo_data.py"
        )
        raise SystemExit(1)

    print("Seeding demo data (30 days, planted anomalies)...")

    # Truncate via raw connection (TRUNCATE bypasses the events append-only trigger)
    with engine.begin() as conn:
        _truncate_all(conn)

    with session_scope() as session:
        # ----- Employees -----
        emps: list[Employee] = []
        for e in EMPLOYEES:
            emp = Employee(name=e["name"], role=e["role"], neocall_id=e["neocall_id"])
            session.add(emp)
            session.flush()
            emps.append(emp)
        print(f"  employees: {len(emps)}")

        # ----- Inventory items -----
        for item in CATALOGUE:
            session.add(InventoryItem(
                sku=item["sku"],
                name=item["name"],
                category=item["category"],
                unit=item["unit"],
                cost_thb=Decimal(str(item["cost"])),
                price_thb=Decimal(str(item["price"])),
            ))
        session.flush()
        print(f"  inventory items: {len(CATALOGUE)}")

        # Initial stock movements (opening 30 days ago)
        start_date = datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0) \
            - timedelta(days=30)
        for item in CATALOGUE:
            session.add(InventoryMovement(
                timestamp=start_date,
                sku=item["sku"],
                movement_type="received",
                quantity=Decimal(RNG.choice([50, 100, 150, 200])),
            ))

        # ----- 30 days of shifts + sales -----
        unmatched_planted = 0
        unmatched_target = 5
        cash_short_planted = 0
        cash_short_target = 2
        shrinkage_planted = False
        void_burst_planted = False

        total_receipts = 0
        total_bank_tx = 0

        for day_offset in range(30):
            day = start_date + timedelta(days=day_offset)

            for shift_idx, (sched_h_start, sched_h_end) in enumerate([(9, 16), (16, 23)]):
                shift_start = day.replace(hour=sched_h_start, minute=0)
                shift_end = day.replace(hour=sched_h_end, minute=30)

                shift_emps = RNG.sample(emps[1:], k=2)  # 2 cashiers per shift
                if shift_idx == 0:
                    shift_emps = [emps[0], shift_emps[0]]  # manager opens

                shift = Shift(
                    scheduled_start=shift_start,
                    scheduled_end=shift_end,
                    actual_start=shift_start + timedelta(minutes=RNG.randint(-5, 15)),
                    actual_end=shift_end + timedelta(minutes=RNG.randint(-10, 20)),
                    employee_ids=[e.id for e in shift_emps],
                    status="closed",
                )
                session.add(shift)
                session.flush()

                # Attendance logs
                for emp in shift_emps:
                    fp_in = shift.actual_start + timedelta(minutes=RNG.randint(-3, 5))
                    fp_out = shift.actual_end + timedelta(minutes=RNG.randint(-2, 10))
                    for fp_time, evt in [(fp_in, "check_in"), (fp_out, "check_out")]:
                        idem = _idem("neocall_seed", emp.neocall_id, fp_time)
                        ev = Event(
                            source="neocall", event_type=f"attendance.{evt}",
                            payload={"employee_id": emp.neocall_id, "fingerprint_time": fp_time.isoformat(), "event": evt},
                            received_at=fp_time, source_timestamp=fp_time,
                            source_id=emp.neocall_id, idempotency_key=idem,
                        )
                        session.add(ev)
                        session.flush()
                        session.add(AttendanceLog(
                            employee_id=emp.id, fingerprint_timestamp=fp_time,
                            event_type=evt, raw_event_id=ev.id,
                        ))

                # Cash session
                opening_cash = Decimal("2000")
                cs = CashSession(
                    shift_id=shift.id, opening_amount=opening_cash, status="closed",
                    opened_at=shift.actual_start, closed_at=shift.actual_end,
                )
                session.add(cs)
                session.flush()

                # POS transactions for the shift
                num_receipts = RNG.randint(20, 45)
                shift_cash_in = Decimal("0")
                for i in range(num_receipts):
                    receipt_time = shift_start + timedelta(
                        minutes=RNG.randint(10, int((shift_end - shift_start).total_seconds() // 60 - 10))
                    )
                    # 1-4 line items per receipt
                    items = RNG.sample(CATALOGUE, k=RNG.randint(1, 4))
                    line_items = []
                    total = Decimal("0")
                    for it in items:
                        qty = 1 if it["unit"] != "g" else RNG.choice([1, 1, 2, 3.5])
                        amt = Decimal(str(it["price"])) * Decimal(str(qty))
                        total += amt
                        line_items.append({
                            "sku": it["sku"], "name": it["name"], "quantity": float(qty),
                            "unit_price": it["price"], "total": float(amt),
                        })

                    # Payment method mix: 55% cash, 40% transfer, 5% mixed
                    roll = RNG.random()
                    if roll < 0.55:
                        method, cash_amt, xfer_amt = "cash", total, Decimal("0")
                    elif roll < 0.95:
                        method, cash_amt, xfer_amt = "transfer", Decimal("0"), total
                    else:
                        xfer_amt = (total / 2).quantize(Decimal("0.01"))
                        cash_amt = total - xfer_amt
                        method = "mixed"

                    employee = RNG.choice(shift_emps)
                    receipt_id = f"R-{day_offset:02d}-{shift_idx}-{i:03d}"
                    idem = _idem("loyverse_seed", receipt_id)
                    ev = Event(
                        source="loyverse", event_type="receipt.upsert",
                        payload={"receipt_number": receipt_id, "total_money": float(total), "line_items": line_items},
                        received_at=receipt_time, source_timestamp=receipt_time,
                        source_id=receipt_id, idempotency_key=idem,
                    )
                    session.add(ev)
                    session.flush()

                    pos = PosTransaction(
                        receipt_id=receipt_id, timestamp=receipt_time, total=total,
                        cash_amount=cash_amt, transfer_amount=xfer_amt, payment_method=method,
                        employee_id=employee.id, shift_id=shift.id,
                        line_items=line_items, raw_event_id=ev.id,
                    )
                    session.add(pos)
                    shift_cash_in += cash_amt
                    total_receipts += 1

                    # Inventory deductions
                    for li in line_items:
                        session.add(InventoryMovement(
                            timestamp=receipt_time, sku=li["sku"],
                            movement_type="sold", quantity=Decimal(str(li["quantity"])),
                            reference_id=receipt_id, shift_id=shift.id,
                        ))

                    # Matching KBank deposit (for transfer/mixed), unless we plant an unmatched
                    if xfer_amt > 0:
                        plant_unmatched = (
                            unmatched_planted < unmatched_target
                            and day_offset >= 22 and shift_idx == 1
                            and RNG.random() < 0.05
                        )
                        if plant_unmatched:
                            unmatched_planted += 1
                        else:
                            bank_ts = receipt_time + timedelta(seconds=RNG.randint(-90, 180))
                            ref = f"KB{day_offset:02d}{shift_idx}{i:03d}"
                            bank_idem = _idem("kbank_seed", bank_ts.isoformat(), xfer_amt, ref)
                            ev2 = Event(
                                source="kbank_sms", event_type="deposit.received",
                                payload={
                                    "amount": float(xfer_amt),
                                    "sender": f"Customer-{RNG.randint(1000, 9999)}",
                                    "ref": ref,
                                },
                                received_at=bank_ts, source_timestamp=bank_ts,
                                idempotency_key=bank_idem,
                            )
                            session.add(ev2)
                            session.flush()
                            session.add(BankTransaction(
                                bank_timestamp=bank_ts, amount=xfer_amt, direction="in",
                                sender=f"Customer-{RNG.randint(1000, 9999)}", ref_number=ref,
                                balance=Decimal(RNG.randint(5000, 100000)),
                                raw_sms=f"K-PLUS: Money in {xfer_amt} THB Ref {ref}",
                                idempotency_key=bank_idem, raw_event_id=ev2.id,
                            ))
                            total_bank_tx += 1

                # Close cash session — plant a shortage on 2 specific shifts
                expected = opening_cash + shift_cash_in
                plant_shortage = (
                    cash_short_planted < cash_short_target
                    and day_offset in (10, 24) and shift_idx == 1
                )
                if plant_shortage:
                    cash_short_planted += 1
                    final = expected - Decimal(RNG.choice([520, 680]))
                else:
                    final = expected + Decimal(RNG.choice([-30, -10, 0, 0, 0, 5, 15]))

                cs.expected_close = expected
                cs.counted_close_1 = final
                cs.counted_close_2 = final
                cs.final_count = final
                cs.discrepancy = expected - final
                session.add(cs)

                if plant_shortage:
                    session.add(Alert(
                        severity="WARN", alert_type="CASH_DISCREPANCY",
                        payload={
                            "shift_id": shift.id,
                            "expected": float(expected),
                            "counted": float(final),
                            "delta": float(expected - final),
                        },
                        financial_impact_thb=expected - final,
                        shift_id=shift.id, created_at=shift.actual_end,
                    ))
                    session.add(Discrepancy(
                        discrepancy_type="CASH_SHORTAGE",
                        shift_id=shift.id,
                        employee_id=shift_emps[0].id,
                        expected=expected, actual=final, delta=expected - final,
                        detected_at=shift.actual_end,
                    ))

                # Plant a void burst on day 19 evening shift
                if not void_burst_planted and day_offset == 19 and shift_idx == 1:
                    void_burst_planted = True
                    from sqlmodel import select as _sel
                    bursts = session.exec(
                        _sel(PosTransaction)
                        .where(PosTransaction.shift_id == shift.id)
                        .limit(6)
                    ).all()
                    burst_emp = bursts[0].employee_id
                    for tx in bursts:
                        tx.void_status = "voided"
                        tx.employee_id = burst_emp
                        session.add(tx)
                    session.add(Alert(
                        severity="WARN", alert_type="VOID_BURST",
                        payload={
                            "employee_id": burst_emp,
                            "void_count": len(bursts),
                            "window_minutes": 30,
                        },
                        shift_id=shift.id, created_at=shift.actual_end,
                    ))

        # Plant inventory shrinkage: 4 Laundry Detergents disappeared during day 25
        if not shrinkage_planted:
            shrink_time = start_date + timedelta(days=25, hours=22)
            session.add(InventoryMovement(
                timestamp=shrink_time, sku="HH-DETERG",
                movement_type="adjusted", quantity=Decimal("-4"),
                reference_id="ADJ-SHRINK-001",
            ))
            session.add(Discrepancy(
                discrepancy_type="INVENTORY_SHRINKAGE",
                sku="HH-DETERG",
                expected=Decimal("4"), actual=Decimal("0"), delta=Decimal("-4"),
                detected_at=shrink_time,
                resolution_notes="4 Laundry Detergents unaccounted for during evening shift",
            ))
            session.add(Alert(
                severity="WARN", alert_type="INVENTORY_SHRINKAGE",
                payload={
                    "sku": "HH-DETERG",
                    "name": "Laundry Detergent",
                    "expected": 4, "actual": 0, "delta_units": -4,
                },
                financial_impact_thb=Decimal("480"),
                created_at=shrink_time,
            ))
            shrinkage_planted = True

        # SMS bridge heartbeat right before "now"
        session.add(SmsBridgeHeartbeat(
            received_at=datetime.now(BKK) - timedelta(minutes=2),
            bridge_id="store-phone-01", battery_pct=87, network_type="wifi",
        ))

    # Run reconciliation across the full 30-day window
    print("  running reconciliation...")
    reconcile_transfers(since=start_date)

    print(f"Done. Seeded {total_receipts} receipts, {total_bank_tx} bank transactions.")
    print(f"  planted: {unmatched_planted} unmatched transfers, {cash_short_planted} cash shortages")
    print("  planted: 1 inventory shrinkage, 1 void burst")
    print("Open Metabase at http://localhost:3000 and connect to the project_ot database")
    print("to add dashboards over public_safe.* views.")


if __name__ == "__main__":
    main()
