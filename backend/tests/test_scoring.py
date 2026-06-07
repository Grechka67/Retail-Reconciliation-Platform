from app.anomaly.scoring import (
    DISCOUNT_RATIO_THRESHOLD,
    discount_ratio,
    refund_zscore,
)


def test_discount_ratio_is_share_of_pre_discount_total():
    # Charged 70 after a 30 discount → original 100 → 30%.
    assert discount_ratio(discount=30, total=70) == 0.30


def test_discount_ratio_is_zero_when_no_sale():
    assert discount_ratio(discount=0, total=0) == 0.0


def test_a_clear_discount_outlier_clears_the_threshold():
    # Charged 40 after a 60 discount → 60% off → well over the 30% rule.
    assert discount_ratio(discount=60, total=40) >= DISCOUNT_RATIO_THRESHOLD


def test_refund_zscore_needs_at_least_five_days_of_history():
    assert refund_zscore(today_count=10, history_counts=[1, 1, 1, 1]) is None


def test_refund_zscore_is_none_when_history_has_no_variance():
    # Every day identical → no baseline spread → z-score is meaningless.
    assert refund_zscore(today_count=99, history_counts=[2, 2, 2, 2, 2]) is None


def test_refund_zscore_flags_a_clear_spike():
    # Baseline ~2/day, today 20 → many standard deviations out.
    z = refund_zscore(today_count=20, history_counts=[2, 3, 1, 2, 3, 2, 1])
    assert z is not None and z > 2.0
