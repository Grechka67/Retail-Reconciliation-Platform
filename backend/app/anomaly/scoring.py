"""Pure anomaly-scoring helpers — no DB, so they are unit-testable.

The rules in rules.py do the SQL; the math that decides whether something is
anomalous lives here.
"""
from __future__ import annotations

from statistics import mean, stdev

VOID_BURST_THRESHOLD = 5          # voids by one employee in 30m
REFUND_Z_THRESHOLD = 2.0          # today's refunds vs 14-day baseline
DISCOUNT_RATIO_THRESHOLD = 0.30   # single-transaction discount as share of pre-discount total


def discount_ratio(discount: float, total: float) -> float:
    """Discount as a fraction of the pre-discount total. `total` is the amount
    actually charged, so the original price is `total + discount`.
    """
    base = float(total) + float(discount)
    return float(discount) / base if base else 0.0


def refund_zscore(today_count: int, history_counts: list[int]) -> float | None:
    """Z-score of today's refund count against the rolling history.

    Returns None when there isn't enough history (<5 days) or there's no
    variance to score against — i.e. when a z-score would be meaningless.
    """
    if len(history_counts) < 5:
        return None
    mu = mean(history_counts)
    sd = stdev(history_counts) if len(history_counts) > 1 else 0
    if sd == 0:
        return None
    return (today_count - mu) / sd
