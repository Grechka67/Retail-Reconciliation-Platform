from decimal import Decimal

from app.ingestion.loyverse_mapping import (
    ACTIVE,
    REFUNDED,
    VOIDED,
    classify_receipt,
    receipt_discount,
)


def test_a_normal_sale_is_active():
    assert classify_receipt({"receipt_type": "SALE"}) == (ACTIVE, None)


def test_a_cancelled_receipt_is_voided():
    assert classify_receipt({"cancelled_at": "2026-06-06T10:00:00Z"}) == (VOIDED, None)


def test_cancellation_wins_over_refund_type():
    # A cancelled REFUND is still a void, not a refund.
    r = {"cancelled_at": "2026-06-06T10:00:00Z", "receipt_type": "REFUND"}
    assert classify_receipt(r) == (VOIDED, None)


def test_a_refund_links_back_to_the_original():
    r = {"receipt_type": "REFUND", "refund_for": "1-1042"}
    assert classify_receipt(r) == (REFUNDED, "1-1042")


def test_a_refund_without_a_reference_still_classifies():
    assert classify_receipt({"receipt_type": "REFUND"}) == (REFUNDED, None)


def test_discount_is_extracted_as_decimal():
    assert receipt_discount({"total_discount": "15.50"}) == Decimal("15.50")


def test_missing_discount_is_zero():
    assert receipt_discount({}) == Decimal("0")


def test_null_discount_is_zero():
    assert receipt_discount({"total_discount": None}) == Decimal("0")
