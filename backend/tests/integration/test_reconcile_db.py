"""Integration tests for transfer reconciliation against a real Postgres."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.db import session_scope
from app.models import BankTransaction, PosTransaction, TransferMatch
from app.reconciliation.transfers import reconcile_transfers

BKK = ZoneInfo("Asia/Bangkok")


def _transfer(receipt_id: str, amount: str, ts: datetime) -> PosTransaction:
    return PosTransaction(
        receipt_id=receipt_id, timestamp=ts, total=Decimal(amount),
        transfer_amount=Decimal(amount), payment_method="transfer", line_items=[],
    )


def _deposit(amount: str, ts: datetime, key: str) -> BankTransaction:
    return BankTransaction(
        bank_timestamp=ts, amount=Decimal(amount), direction="in", idempotency_key=key,
    )


def test_one_deposit_cannot_verify_two_equal_transfers():
    """Two equal-amount transfers + a single matching deposit must not both
    verify against that one deposit."""
    ts = datetime.now(BKK) - timedelta(seconds=120)
    with session_scope() as s:
        s.add(_transfer("R-A", "777.77", ts))
        s.add(_transfer("R-B", "777.77", ts))
        s.add(_deposit("777.77", ts, "bank-1"))

    reconcile_transfers()

    with session_scope() as s:
        deposit = s.exec(select(BankTransaction)).one()
        verified = s.exec(
            select(TransferMatch)
            .where(TransferMatch.status == "VERIFIED")
            .where(TransferMatch.bank_transaction_id == deposit.id)
        ).all()
    assert len(verified) == 1


def test_single_transfer_with_one_deposit_verifies():
    """The guard must not block the normal 1-to-1 case."""
    ts = datetime.now(BKK) - timedelta(seconds=120)
    with session_scope() as s:
        s.add(_transfer("R-A", "512.00", ts))
        s.add(_deposit("512.00", ts, "bank-1"))

    reconcile_transfers()

    with session_scope() as s:
        match = s.exec(
            select(TransferMatch).where(TransferMatch.pos_transaction_id == "R-A")
        ).one()
        deposit = s.exec(select(BankTransaction)).one()
        status, matched_bank_id = match.status, match.bank_transaction_id
        deposit_id = deposit.id
    assert status == "VERIFIED"
    assert matched_bank_id == deposit_id
