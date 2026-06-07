"""Admin / manager endpoints — used by the admin UI and cashier PWA."""
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.security import require_admin
from app.models import (
    Alert,
    CashSession,
    Discrepancy,
    InventoryCount,
    Shift,
    ShiftSalesReport,
)

# Every route on this router requires a valid X-API-Key.
router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/shifts")
def list_shifts(session: Session = Depends(get_session)):
    return session.exec(select(Shift).order_by(Shift.scheduled_start.desc()).limit(50)).all()


@router.post("/shifts")
def create_shift(payload: dict[str, Any], session: Session = Depends(get_session)):
    shift = Shift(
        scheduled_start=datetime.fromisoformat(payload["scheduled_start"]),
        scheduled_end=datetime.fromisoformat(payload["scheduled_end"]),
        employee_ids=payload["employee_ids"],
    )
    session.add(shift)
    session.commit()
    session.refresh(shift)
    return shift


@router.get("/alerts/open")
def open_alerts(session: Session = Depends(get_session)):
    return session.exec(
        select(Alert).where(Alert.acked_at.is_(None)).order_by(Alert.created_at.desc())
    ).all()


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, payload: dict[str, Any], session: Session = Depends(get_session)):
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "alert not found")
    alert.acked_at = datetime.now(alert.created_at.tzinfo)
    alert.acked_by = payload.get("employee_id")
    session.add(alert)
    session.commit()
    return {"status": "ok"}


@router.post("/cash-sessions/{session_id}/close")
def close_cash_session(
    session_id: int,
    payload: dict[str, Any],
    session: Session = Depends(get_session),
):
    """Blind double-entry close: payload has counted_close_1 and counted_close_2 (must match)."""
    cs = session.get(CashSession, session_id)
    if not cs:
        raise HTTPException(404, "cash session not found")
    c1 = Decimal(str(payload["counted_close_1"]))
    c2 = Decimal(str(payload["counted_close_2"]))
    if c1 != c2:
        raise HTTPException(400, "double-entry mismatch — recount required")
    now = datetime.now(cs.opened_at.tzinfo)
    cs.counted_close_1 = c1
    cs.counted_close_2 = c2
    cs.final_count = c1
    cs.discrepancy = (cs.expected_close or Decimal("0")) - c1
    cs.status = "closed"
    cs.closed_at = now
    session.add(cs)

    # Flag a material discrepancy for manager review. This is the only place
    # final_count/discrepancy exist, so the alert is raised here, not in the
    # scheduled cash job (which only precomputes expected_close).
    s = get_settings()
    if abs(cs.discrepancy) >= Decimal(str(s.anomaly_cash_threshold_thb)):
        session.add(Alert(
            severity="WARN",
            alert_type="CASH_DISCREPANCY",
            payload={
                "shift_id": cs.shift_id,
                "expected": float(cs.expected_close or 0),
                "counted": float(cs.final_count or 0),
                "delta": float(cs.discrepancy),
            },
            financial_impact_thb=cs.discrepancy,
            shift_id=cs.shift_id,
            created_at=now,
        ))
        session.add(Discrepancy(
            discrepancy_type="CASH_SHORTAGE" if cs.discrepancy > 0 else "CASH_OVER",
            shift_id=cs.shift_id,
            expected=cs.expected_close,
            actual=cs.final_count,
            delta=cs.discrepancy,
            detected_at=now,
        ))

    session.commit()
    return cs


@router.post("/inventory/counts")
def submit_inventory_count(payload: dict[str, Any], session: Session = Depends(get_session)):
    """Staff PWA submits opening / closing counts (blind double-entry)."""
    c1 = Decimal(str(payload["counted_value_1"]))
    c2 = Decimal(str(payload["counted_value_2"]))
    if c1 != c2:
        raise HTTPException(400, "double-entry mismatch — recount required")
    count = InventoryCount(
        shift_id=payload["shift_id"],
        sku=payload["sku"],
        count_type=payload["count_type"],
        counted_value_1=c1,
        counted_value_2=c2,
        final_value=c1,
        counted_by=payload.get("counted_by"),
        counted_at=datetime.fromisoformat(payload["counted_at"]),
    )
    session.add(count)
    session.commit()
    session.refresh(count)
    return count


@router.post("/shift-sales-reports")
def submit_sales_report(payload: dict[str, Any], session: Session = Depends(get_session)):
    """Cashier's recall of what they sold during the shift."""
    report = ShiftSalesReport(
        shift_id=payload["shift_id"],
        employee_id=payload["employee_id"],
        sku=payload["sku"],
        reported_quantity=Decimal(str(payload["reported_quantity"])),
        reported_at=datetime.fromisoformat(payload["reported_at"]),
        notes=payload.get("notes"),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report
