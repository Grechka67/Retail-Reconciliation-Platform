"""KBank deposit SMS parser.

Real KBank deposit SMS samples (Thai bank notification format):

    "K-PLUS: Money in 1,250.00 THB from John Doe at 21:13 on 19/05/26.
     Balance 8,420.50 THB. Ref 202605192113AB"

    "เงินเข้า 850.00 บาท จาก สมชาย ใจดี เวลา 14:25 น. วันที่ 19/05/69
     ยอดคงเหลือ 9,300.50 บาท Ref XYZ123"

Both formats are matched. The KBank SMS format has changed historically;
validate against real samples from the store's phone before going live.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

BKK = ZoneInfo("Asia/Bangkok")

_AMOUNT_RE_EN = re.compile(
    r"Money\s+in\s+([\d,]+\.\d{2})\s*THB\s+from\s+([^\.]+?)\s+at\s+(\d{1,2}:\d{2})\s+on\s+(\d{1,2}/\d{1,2}/\d{2})",
    re.IGNORECASE,
)
_AMOUNT_RE_TH = re.compile(
    r"เงินเข้า\s+([\d,]+\.\d{2})\s*บาท\s+จาก\s+(.+?)\s+เวลา\s+(\d{1,2}:\d{2}).+?วันที่\s+(\d{1,2}/\d{1,2}/\d{2})",
)
_BALANCE_RE = re.compile(r"(?:Balance|ยอดคงเหลือ)\s+([\d,]+\.\d{2})", re.IGNORECASE)
_REF_RE = re.compile(r"Ref\s+([A-Za-z0-9]+)", re.IGNORECASE)


def _to_decimal(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def _parse_thai_date(date_str: str, _today: "datetime.date | None" = None) -> datetime.date:
    """Handles both Gregorian (19/05/26) and Buddhist (19/05/69) date formats.
    The store's KBank account may send either depending on locale settings.

    A 2-digit year is inherently ambiguous ('69' = Gregorian 2069 OR Buddhist 2569),
    so we pick the reading that isn't implausibly far in the future — SMS are near
    real-time. Gregorian = 2000+yy; Buddhist = 2500+yy-543 = 1957+yy."""
    d, m, y = (int(x) for x in date_str.split("/"))
    today = _today or datetime.now(BKK).date()
    if 2000 + y > today.year + 1:   # too far ahead → it's a Buddhist-era year
        year = 1957 + y
    else:
        year = 2000 + y
    return datetime(year, m, d).date()


def parse_kbank_sms(text: str) -> dict | None:
    """Returns {'amount', 'sender', 'bank_timestamp', 'balance', 'ref'} or None."""
    m = _AMOUNT_RE_EN.search(text) or _AMOUNT_RE_TH.search(text)
    if not m:
        return None
    amount = _to_decimal(m.group(1))
    sender = m.group(2).strip()
    time_str = m.group(3)
    date_str = m.group(4)

    date_part = _parse_thai_date(date_str)
    hour, minute = (int(x) for x in time_str.split(":"))
    bank_ts = datetime(date_part.year, date_part.month, date_part.day, hour, minute, tzinfo=BKK)

    balance = None
    bm = _BALANCE_RE.search(text)
    if bm:
        balance = _to_decimal(bm.group(1))

    ref = None
    rm = _REF_RE.search(text)
    if rm:
        ref = rm.group(1)

    return {
        "sender": sender,
        "amount": float(amount),
        "bank_timestamp": bank_ts,
        "balance": float(balance) if balance is not None else None,
        "ref": ref,
    }
