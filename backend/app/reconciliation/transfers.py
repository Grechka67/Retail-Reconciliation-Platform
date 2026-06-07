"""Transfer reconciliation.

For each transfer-method POS transaction, find the matching KBank deposit
within ±N seconds and the same amount. Outcomes:

    VERIFIED            exactly one match in window
    UNMATCHED           no candidate (raises WARN alert after grace period)
    POSSIBLE_DUPLICATE  multiple candidates (raises WARN alert, manager review)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.models import Alert, BankTransaction, PosTransaction, TransferMatch
from app.reconciliation.matching import (
    PENDING,
    POSSIBLE_DUPLICATE,
    VERIFIED,
    classify_match,
    confidence_for_delta,
)

log = logging.getLogger("ot.reconcile.transfers")
BKK = ZoneInfo("Asia/Bangkok")


def reconcile_transfers(since: datetime | None = None) -> None:
    s = get_settings()
    window = timedelta(seconds=s.transfer_match_window_seconds)
    if since is None:
        since = datetime.now(BKK) - timedelta(hours=24)
    now = datetime.now(BKK)

    new_matches = 0
    new_unmatched = 0
    new_dupes = 0

    with session_scope() as session:
        candidates = session.exec(
            select(PosTransaction)
            .where(PosTransaction.payment_method.in_(["transfer", "mixed"]))
            .where(PosTransaction.timestamp >= since)
            .where(PosTransaction.void_status == "active")
        ).all()

        # Deposits claimed earlier in THIS run. The session is autoflush=False,
        # so a match added this loop isn't visible to the taken_ids query below
        # until commit — without this, two equal-amount receipts in the same
        # window both verify against the same deposit.
        claimed: set[int] = set()

        for pos in candidates:
            existing = session.exec(
                select(TransferMatch).where(TransferMatch.pos_transaction_id == pos.receipt_id)
            ).first()
            if existing and existing.status == "VERIFIED":
                continue

            target = pos.transfer_amount if pos.transfer_amount > 0 else pos.total
            window_start = pos.timestamp - window
            window_end = pos.timestamp + window
            bank_candidates = session.exec(
                select(BankTransaction)
                .where(BankTransaction.amount == Decimal(target))
                .where(BankTransaction.bank_timestamp >= window_start)
                .where(BankTransaction.bank_timestamp <= window_end)
                .where(BankTransaction.direction == "in")
            ).all()

            # Filter out bank tx already matched to other receipts
            taken_ids = {m.bank_transaction_id for m in session.exec(
                select(TransferMatch).where(TransferMatch.bank_transaction_id.in_(
                    [b.id for b in bank_candidates] or [-1]
                ))
            ).all() if m.bank_transaction_id}
            bank_candidates = [
                b for b in bank_candidates
                if b.id not in taken_ids and b.id not in claimed
            ]

            age = (now - pos.timestamp).total_seconds()
            status = classify_match(len(bank_candidates), age, s.transfer_match_window_seconds)

            if status == VERIFIED:
                b = bank_candidates[0]
                claimed.add(b.id)
                delta = abs((b.bank_timestamp - pos.timestamp).total_seconds())
                match = existing or TransferMatch(pos_transaction_id=pos.receipt_id, matched_at=now)
                match.bank_transaction_id = b.id
                match.status = VERIFIED
                match.confidence = confidence_for_delta(delta)
                match.time_delta_seconds = int(delta)
                match.matched_at = now
                session.add(match)
                new_matches += 1

            elif status == POSSIBLE_DUPLICATE:
                match = existing or TransferMatch(pos_transaction_id=pos.receipt_id, matched_at=now)
                match.bank_transaction_id = None
                match.status = POSSIBLE_DUPLICATE
                match.confidence = Decimal("0.50")
                match.matched_at = now
                session.add(match)
                new_dupes += 1
                _raise_alert(session, "POSSIBLE_DUPLICATE_TRANSFER", pos, target, now)

            elif status == PENDING:
                continue  # still inside grace window

            else:  # UNMATCHED
                match = existing or TransferMatch(pos_transaction_id=pos.receipt_id, matched_at=now)
                match.bank_transaction_id = None
                match.status = "UNMATCHED"
                match.confidence = Decimal("0.00")
                match.matched_at = now
                session.add(match)
                new_unmatched += 1
                _raise_alert(session, "UNMATCHED_TRANSFER", pos, target, now)

    if new_matches or new_unmatched or new_dupes:
        log.info(
            "Reconciliation: %d verified, %d unmatched, %d duplicates",
            new_matches, new_unmatched, new_dupes,
        )


def _raise_alert(session, alert_type: str, pos: PosTransaction, amount, now) -> None:
    from sqlmodel import select
    existing = session.exec(
        select(Alert)
        .where(Alert.alert_type == alert_type)
        .where(Alert.payload["receipt_id"].astext == pos.receipt_id)
        .where(Alert.acked_at.is_(None))
    ).first()
    if existing:
        return
    session.add(Alert(
        severity="WARN",
        alert_type=alert_type,
        payload={
            "receipt_id": pos.receipt_id,
            "amount_thb": float(amount),
            "pos_timestamp": pos.timestamp.isoformat(),
            "shift_id": pos.shift_id,
        },
        financial_impact_thb=amount,
        shift_id=pos.shift_id,
        created_at=now,
    ))
