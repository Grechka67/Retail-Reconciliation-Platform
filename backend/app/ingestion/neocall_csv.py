"""NeoCall fingerprint CSV importer.

Expected CSV columns (NeoCall default export):
    employee_id, employee_name, fingerprint_time, event
"""
from __future__ import annotations

import csv
from datetime import datetime
from hashlib import sha256
from io import StringIO
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import AttendanceLog, Employee, Event

BKK = ZoneInfo("Asia/Bangkok")


def import_neocall_csv(text: str, session: Session) -> dict:
    reader = csv.DictReader(StringIO(text))
    inserted = 0
    skipped = 0

    for row in reader:
        neocall_id = (row.get("employee_id") or "").strip()
        fp_time_raw = (row.get("fingerprint_time") or "").strip()
        event_type = (row.get("event") or "check_in").strip().lower()
        if not neocall_id or not fp_time_raw:
            continue

        fp_ts = datetime.fromisoformat(fp_time_raw)
        if fp_ts.tzinfo is None:
            fp_ts = fp_ts.replace(tzinfo=BKK)

        emp = session.exec(select(Employee).where(Employee.neocall_id == neocall_id)).first()
        if emp is None:
            emp = Employee(name=row.get("employee_name") or neocall_id, neocall_id=neocall_id)
            session.add(emp)
            session.flush()

        idem = sha256(f"neocall|{neocall_id}|{fp_ts.isoformat()}|{event_type}".encode()).hexdigest()
        existing = session.exec(select(Event).where(Event.idempotency_key == idem)).first()
        if existing:
            skipped += 1
            continue

        event = Event(
            source="neocall",
            event_type=f"attendance.{event_type}",
            payload=row,
            received_at=datetime.now(BKK),
            source_timestamp=fp_ts,
            source_id=neocall_id,
            idempotency_key=idem,
        )
        session.add(event)
        session.flush()

        session.add(AttendanceLog(
            employee_id=emp.id,
            fingerprint_timestamp=fp_ts,
            event_type=event_type,
            raw_event_id=event.id,
        ))
        inserted += 1

    session.commit()
    return {"inserted": inserted, "skipped": skipped}
