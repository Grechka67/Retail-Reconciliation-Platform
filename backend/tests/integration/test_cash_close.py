"""Integration tests for cash-session close against a real Postgres."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.api.admin import close_cash_session
from app.db import SessionLocal, session_scope
from app.models import Alert, CashSession, Shift

BKK = ZoneInfo("Asia/Bangkok")


def _open_cash_session(expected_close: str) -> int:
    """Create a shift + open cash session with a known expected_close; return its id."""
    now = datetime.now(BKK)
    with session_scope() as s:
        shift = Shift(
            scheduled_start=now - timedelta(hours=8),
            scheduled_end=now - timedelta(minutes=5),
            employee_ids=[],
        )
        s.add(shift)
        s.flush()
        cs = CashSession(
            shift_id=shift.id, opening_amount=Decimal("0"),
            expected_close=Decimal(expected_close), status="open", opened_at=now,
        )
        s.add(cs)
        s.flush()
        return cs.id


def _close(cs_id: int, counted: str):
    sess = SessionLocal()
    try:
        close_cash_session(cs_id, {"counted_close_1": counted, "counted_close_2": counted}, sess)
    finally:
        sess.close()


def test_shortage_over_threshold_raises_alert():
    """Closing a session well short of expected must flag a CASH_DISCREPANCY."""
    cs_id = _open_cash_session("1000")  # expected 1000, count 600 -> 400 short (> 300)
    _close(cs_id, "600")

    with session_scope() as s:
        alerts = s.exec(
            select(Alert).where(Alert.alert_type == "CASH_DISCREPANCY")
        ).all()
        impacts = [a.financial_impact_thb for a in alerts]
    assert len(alerts) == 1
    assert impacts[0] == Decimal("400.00")


def test_shortage_within_threshold_does_not_alert():
    """A small discrepancy under the threshold must not flag."""
    cs_id = _open_cash_session("1000")  # expected 1000, count 900 -> 100 short (< 300)
    _close(cs_id, "900")

    with session_scope() as s:
        alerts = s.exec(
            select(Alert).where(Alert.alert_type == "CASH_DISCREPANCY")
        ).all()
    assert alerts == []
