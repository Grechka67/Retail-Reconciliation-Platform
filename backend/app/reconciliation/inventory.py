"""Inventory reconciliation — expected vs counted per SKU per shift."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.db import session_scope
from app.models import (
    Alert,
    Discrepancy,
    InventoryCount,
    InventoryItem,
    InventoryMovement,
    Shift,
)

log = logging.getLogger("ot.reconcile.inventory")
BKK = ZoneInfo("Asia/Bangkok")


def reconcile_inventory_for_shift(shift_id: int) -> list[Discrepancy]:
    """Called when a closing inventory count is submitted for a shift."""
    out: list[Discrepancy] = []
    now = datetime.now(BKK)

    with session_scope() as session:
        opening = {c.sku: c for c in session.exec(
            select(InventoryCount).where(InventoryCount.shift_id == shift_id)
            .where(InventoryCount.count_type == "opening")
        ).all()}
        closing = {c.sku: c for c in session.exec(
            select(InventoryCount).where(InventoryCount.shift_id == shift_id)
            .where(InventoryCount.count_type == "closing")
        ).all()}

        shift = session.get(Shift, shift_id)
        if not shift:
            return out

        for sku, open_count in opening.items():
            close_count = closing.get(sku)
            if close_count is None:
                continue

            movements = session.exec(
                select(InventoryMovement)
                .where(InventoryMovement.sku == sku)
                .where(InventoryMovement.timestamp >= shift.scheduled_start)
                .where(InventoryMovement.timestamp <= (shift.actual_end or shift.scheduled_end))
            ).all()

            received = sum(m.quantity for m in movements if m.movement_type == "received")
            sold = sum(m.quantity for m in movements if m.movement_type == "sold")
            damaged = sum(m.quantity for m in movements if m.movement_type == "damaged")

            expected = open_count.final_value + received - sold - damaged
            actual = close_count.final_value
            delta = expected - actual

            if abs(delta) < Decimal("0.001"):
                continue

            item = session.get(InventoryItem, sku)
            value_thb = (item.price_thb or Decimal("0")) * delta if item else None

            disc = Discrepancy(
                discrepancy_type="INVENTORY_SHRINKAGE",
                shift_id=shift_id,
                sku=sku,
                expected=expected,
                actual=actual,
                delta=delta,
                detected_at=now,
            )
            session.add(disc)
            out.append(disc)

            session.add(Alert(
                severity="WARN" if abs(delta) >= Decimal("1") else "INFO",
                alert_type="INVENTORY_SHRINKAGE",
                payload={
                    "sku": sku,
                    "name": item.name if item else None,
                    "expected": float(expected),
                    "actual": float(actual),
                    "delta_units": float(delta),
                },
                financial_impact_thb=value_thb,
                shift_id=shift_id,
                created_at=now,
            ))
            log.info("Shrinkage %s on shift %s: %s units", sku, shift_id, delta)

    return out
