from decimal import Decimal

from app.reconciliation.matching import (
    PENDING,
    POSSIBLE_DUPLICATE,
    UNMATCHED,
    VERIFIED,
    classify_match,
    confidence_for_delta,
)

WINDOW = 600  # seconds


def test_single_candidate_is_verified():
    assert classify_match(1, age_seconds=30, window_seconds=WINDOW) == VERIFIED


def test_multiple_candidates_are_possible_duplicate():
    # Two bank deposits of the same amount in-window — can't safely auto-match.
    assert classify_match(2, age_seconds=30, window_seconds=WINDOW) == POSSIBLE_DUPLICATE


def test_zero_candidates_inside_grace_window_is_pending():
    # No deposit yet, but the transfer is younger than the window — give it time.
    assert classify_match(0, age_seconds=WINDOW - 1, window_seconds=WINDOW) == PENDING


def test_zero_candidates_past_grace_window_is_unmatched():
    # Past the window with no deposit → flag it.
    assert classify_match(0, age_seconds=WINDOW + 1, window_seconds=WINDOW) == UNMATCHED


def test_confidence_is_higher_for_tighter_time_gap():
    assert confidence_for_delta(59) == Decimal("0.99")
    assert confidence_for_delta(60) == Decimal("0.90")  # boundary is exclusive
    assert confidence_for_delta(300) == Decimal("0.90")
