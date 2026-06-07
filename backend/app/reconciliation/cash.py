"""Cash drawer reconciliation — expected vs counted at shift close."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.db import session_scope
from app.models import CashSession, PosTransaction, Shift

log = logging.getLogger("ot.reconcile.cash")
BKK = ZoneInfo("Asia/Bangkok")


def close_eligible_cash_sessions() -> None:
    """Compute expected_close for any open session whose shift has ended.

    Once the cashier submits counted_close_1 and counted_close_2 via
    /admin/cash-sessions/{id}/close (blind double-entry), discrepancy
    is computed there. This job only fills in expected_close so the
    manager-facing dashboard can show the gap before the count is in.
    """
    now = datetime.now(BKK)

    with session_scope() as session:
        open_sessions = session.exec(
            select(CashSession).where(CashSession.status == "open")
        ).all()

        for cs in open_sessions:
            shift = session.get(Shift, cs.shift_id)
            if not shift or shift.scheduled_end > now:
                continue

            cash_revenue = sum(
                (p.cash_amount or Decimal("0")) for p in session.exec(
                    select(PosTransaction).where(PosTransaction.shift_id == cs.shift_id)
                ).all()
            )
            cs.expected_close = (cs.opening_amount or Decimal("0")) + cash_revenue
            session.add(cs)
