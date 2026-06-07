from datetime import date

from app.ingestion.sms_parser import parse_kbank_sms, _parse_thai_date


def test_parses_english_kplus_format():
    sms = (
        "K-PLUS: Money in 1,250.00 THB from John Doe at 21:13 on 19/05/26. "
        "Balance 8,420.50 THB. Ref 202605192113AB"
    )
    parsed = parse_kbank_sms(sms)
    assert parsed is not None
    assert parsed["amount"] == 1250.0
    assert parsed["sender"] == "John Doe"
    assert parsed["balance"] == 8420.5
    assert parsed["ref"] == "202605192113AB"
    assert parsed["bank_timestamp"].hour == 21
    assert parsed["bank_timestamp"].minute == 13


def test_returns_none_on_garbage():
    assert parse_kbank_sms("this is not a deposit sms") is None


def test_parses_thai_format_with_e_prefixed_sender():
    # Sender name contains เ (common: เอก, เมธี). Must not be dropped (regression).
    sms = (
        "เงินเข้า 850.00 บาท จาก เอกชัย ใจดี เวลา 14:25 น. "
        "วันที่ 19/05/69 ยอดคงเหลือ 9,300.50 บาท Ref XYZ123"
    )
    parsed = parse_kbank_sms(sms)
    assert parsed is not None
    assert parsed["amount"] == 850.0
    assert parsed["sender"] == "เอกชัย ใจดี"
    assert parsed["bank_timestamp"].year == 2026  # BE 2569 → CE 2026
    assert parsed["ref"] == "XYZ123"


def test_buddhist_era_boundary_disambiguation():
    fixed = date(2026, 6, 4)
    assert _parse_thai_date("19/05/26", _today=fixed) == date(2026, 5, 19)  # Gregorian
    assert _parse_thai_date("19/05/69", _today=fixed) == date(2026, 5, 19)  # BE 2569
    assert _parse_thai_date("19/05/60", _today=fixed) == date(2017, 5, 19)  # BE 2560 (was 2060)
