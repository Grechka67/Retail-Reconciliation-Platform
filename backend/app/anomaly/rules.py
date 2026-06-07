"""Rules-based anomaly detection.

Sufficient for the demo and the first 6 months of operation. Each rule
emits an Alert + Discrepancy when triggered, framed in the UI as an
"AI-detected anomaly" (heuristics are AI, just transparent ones).

Upgrade path once 90+ days of clean data exist:
    - z-score against rolling per-shift baselines (per-employee, per-hour)
    - IsolationForest on the same features
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import logging
from statistics import mean
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.anomaly.scoring import (
    DISCOUNT_RATIO_THRESHOLD,
    REFUND_Z_THRESHOLD,
    VOID_BURST_THRESHOLD,
    discount_ratio,
    refund_zscore,
)
from app.db import session_scope
from app.models import Alert, PosTransaction

log = logging.getLogger("ot.anomaly")
BKK = ZoneInfo("Asia/Bangkok")


def scan_for_anomalies() -> None:
    now = datetime.now(BKK)
    _scan_void_burst(now)
    _scan_refund_spike(now)
    _scan_discount_outliers(now)


def _scan_void_burst(now: datetime) -> None:
    """5+ voids by the same employee in a 30-minute window."""
    threshold = VOID_BURST_THRESHOLD
    window = timedelta(minutes=30)
    since = now - window

    with session_scope() as session:
        voids = session.exec(
            select(PosTransaction)
            .where(PosTransaction.void_status == "voided")
            .where(PosTransaction.timestamp >= since)
        ).all()
        by_employee: dict[int, int] = defaultdict(int)
        for v in voids:
            if v.employee_id:
                by_employee[v.employee_id] += 1

        for emp_id, n in by_employee.items():
            if n < threshold:
                continue
            existing = session.exec(
                select(Alert)
                .where(Alert.alert_type == "VOID_BURST")
                .where(Alert.payload["employee_id"].as_integer() == emp_id)
                .where(Alert.created_at >= since)
            ).first()
            if existing:
                continue
            session.add(Alert(
                severity="WARN",
                alert_type="VOID_BURST",
                payload={"employee_id": emp_id, "void_count": n, "window_minutes": 30},
                created_at=now,
            ))
            log.warning("Void burst: employee %s, %d voids in 30m", emp_id, n)


def _scan_refund_spike(now: datetime) -> None:
    """Refunds today vs 14-day rolling average, z-score > 2."""
    today = now.date()
    with session_scope() as session:
        history = session.exec(
            select(PosTransaction)
            .where(PosTransaction.void_status == "refunded")
            .where(PosTransaction.timestamp >= now - timedelta(days=15))
        ).all()
        by_day: dict[str, int] = defaultdict(int)
        for r in history:
            by_day[r.timestamp.date().isoformat()] += 1

        today_count = by_day.get(today.isoformat(), 0)
        history_counts = [v for k, v in by_day.items() if k != today.isoformat()]
        z = refund_zscore(today_count, history_counts)
        if z is None or z < REFUND_Z_THRESHOLD:
            return
        mu = mean(history_counts)

        existing = session.exec(
            select(Alert)
            .where(Alert.alert_type == "REFUND_SPIKE")
            .where(Alert.created_at >= now - timedelta(hours=12))
        ).first()
        if existing:
            return
        session.add(Alert(
            severity="WARN",
            alert_type="REFUND_SPIKE",
            payload={"today_refunds": today_count, "avg_14d": round(mu, 2), "z_score": round(z, 2)},
            created_at=now,
        ))
        log.warning("Refund spike: %d today (mean %.1f, z=%.1f)", today_count, mu, z)


def _scan_discount_outliers(now: datetime) -> None:
    """Single transaction discount > 30% of total."""
    since = now - timedelta(hours=2)
    with session_scope() as session:
        recent = session.exec(
            select(PosTransaction)
            .where(PosTransaction.timestamp >= since)
            .where(PosTransaction.discount_amount > 0)
        ).all()
        for tx in recent:
            if tx.total == 0:
                continue
            ratio = discount_ratio(tx.discount_amount, tx.total)
            if ratio < DISCOUNT_RATIO_THRESHOLD:
                continue
            existing = session.exec(
                select(Alert)
                .where(Alert.alert_type == "EXCESSIVE_DISCOUNT")
                .where(Alert.payload["receipt_id"].astext == tx.receipt_id)
            ).first()
            if existing:
                continue
            session.add(Alert(
                severity="INFO",
                alert_type="EXCESSIVE_DISCOUNT",
                payload={
                    "receipt_id": tx.receipt_id,
                    "discount_thb": float(tx.discount_amount),
                    "total_thb": float(tx.total),
                    "discount_pct": round(ratio * 100, 1),
                    "employee_id": tx.employee_id,
                },
                financial_impact_thb=tx.discount_amount,
                shift_id=tx.shift_id,
                created_at=now,
            ))
