"""Simulate KBank SMS forwarder POSTs to the webhook (for testing without real phone).

Run inside backend container:
    python scripts/sms_simulator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hmac
import json
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

BKK = ZoneInfo("Asia/Bangkok")
ENDPOINT = "http://localhost:8000/ingest/kbank/sms"


def post_sample_sms(text: str) -> None:
    s = get_settings()
    payload = {"text": text, "received_at": datetime.now(BKK).isoformat()}
    body = json.dumps(payload).encode()
    signature = hmac.new(s.kbank_sms_hmac_secret.encode(), body, sha256).hexdigest()
    r = httpx.post(
        ENDPOINT,
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
        timeout=10,
    )
    print(r.status_code, r.json())


if __name__ == "__main__":
    samples = [
        "K-PLUS: Money in 1,250.00 THB from John Doe at 21:13 on 19/05/26. "
        "Balance 8,420.50 THB. Ref 202605192113AB",
        "K-PLUS: Money in 850.00 THB from Customer-4421 at 14:25 on 19/05/26. "
        "Balance 9,270.50 THB. Ref XYZ123",
    ]
    for s in samples:
        post_sample_sms(s)
