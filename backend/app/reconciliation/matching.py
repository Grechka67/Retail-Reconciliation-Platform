"""Pure transfer-matching decision logic — no DB, so it is unit-testable.

`reconcile_transfers` (in transfers.py) does the SQL; the *decisions* it makes
about each POS transaction live here, where they can be tested in isolation.
"""
from __future__ import annotations

from decimal import Decimal

VERIFIED = "VERIFIED"
POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
UNMATCHED = "UNMATCHED"
PENDING = "PENDING"  # zero candidates but still inside the grace window — no record yet


def classify_match(candidate_count: int, age_seconds: float, window_seconds: int) -> str:
    """Given how many bank deposits matched a POS transfer (on exact amount +
    time window) and how old the transfer is, decide its reconciliation status.
    """
    if candidate_count == 1:
        return VERIFIED
    if candidate_count > 1:
        return POSSIBLE_DUPLICATE
    if age_seconds < window_seconds:
        return PENDING  # a real deposit may still arrive — don't flag yet
    return UNMATCHED


def confidence_for_delta(delta_seconds: float) -> Decimal:
    """Confidence of a verified match: tighter time gap → higher confidence."""
    return Decimal("0.99") if delta_seconds < 60 else Decimal("0.90")
