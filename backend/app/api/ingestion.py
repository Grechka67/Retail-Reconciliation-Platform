"""Ingestion endpoints — every source writes to the append-only `events` table first."""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import hmac
import logging
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.models import Event, BankTransaction, SmsBridgeHeartbeat
from app.ingestion.sms_parser import parse_kbank_sms
from app.security import require_admin

log = logging.getLogger("ot.ingest")
router = APIRouter()


def _now_bkk() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def _verify_hmac(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    digest = hmac.new(secret.encode(), body, sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


@router.post("/kbank/sms")
async def kbank_sms_webhook(
    request: Request,
    x_signature: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    """KBank deposit SMS forwarded by the bridge phone. HMAC-signed."""
    body = await request.body()
    settings = get_settings()
    if not _verify_hmac(settings.kbank_sms_hmac_secret, body, x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload: dict[str, Any] = await request.json()
    sms_text = payload.get("text") or ""
    received_ts_raw = payload.get("received_at")

    parsed = parse_kbank_sms(sms_text)
    if not parsed:
        log.warning("Could not parse KBank SMS: %s", sms_text[:120])
        raise HTTPException(status_code=400, detail="could not parse SMS")

    received_at = (
        datetime.fromisoformat(received_ts_raw) if received_ts_raw else _now_bkk()
    )
    idem = sha256(
        f"{parsed['sender']}|{parsed['bank_timestamp']}|{parsed['amount']}|{parsed.get('ref','')}"
        .encode()
    ).hexdigest()

    existing = session.exec(
        BankTransaction.__table__.select().where(BankTransaction.idempotency_key == idem)  # type: ignore
    ).first()
    if existing:
        return {"status": "duplicate", "idempotency_key": idem}

    event = Event(
        source="kbank_sms",
        event_type="deposit.received",
        payload=payload,
        received_at=received_at,
        source_timestamp=parsed["bank_timestamp"],
        idempotency_key=idem,
    )
    session.add(event)
    session.flush()

    bank_tx = BankTransaction(
        bank_timestamp=parsed["bank_timestamp"],
        amount=Decimal(str(parsed["amount"])),
        direction="in",
        sender=parsed["sender"],
        ref_number=parsed.get("ref"),
        balance=Decimal(str(parsed["balance"])) if parsed.get("balance") else None,
        raw_sms=sms_text,
        idempotency_key=idem,
        raw_event_id=event.id,
    )
    session.add(bank_tx)
    session.commit()
    log.info("Ingested KBank deposit: %s THB at %s", parsed["amount"], parsed["bank_timestamp"])
    return {"status": "ok", "bank_transaction_id": bank_tx.id}


@router.post("/kbank/heartbeat")
async def kbank_heartbeat(
    payload: dict[str, Any],
    x_signature: str | None = Header(default=None),
    request: Request = None,
    session: Session = Depends(get_session),
):
    """SMS-bridge phone reports it is alive every 5 minutes."""
    body = await request.body() if request else b""
    settings = get_settings()
    if not _verify_hmac(settings.kbank_sms_hmac_secret, body, x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    hb = SmsBridgeHeartbeat(
        received_at=_now_bkk(),
        bridge_id=payload.get("bridge_id", "default"),
        battery_pct=payload.get("battery_pct"),
        network_type=payload.get("network_type"),
    )
    session.add(hb)
    session.commit()
    return {"status": "ok"}


@router.post("/neocall/csv")
async def neocall_csv_upload(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """NeoCall fingerprint export — manager drops the CSV here."""
    from app.ingestion.neocall_csv import import_neocall_csv
    contents = (await file.read()).decode("utf-8-sig")
    result = import_neocall_csv(contents, session)
    return {"status": "ok", **result}


@router.post("/admin/manual-deposit", dependencies=[Depends(require_admin)])
async def manual_deposit(
    payload: dict[str, Any],
    session: Session = Depends(get_session),
):
    """Manager fallback for KBank deposits when the SMS bridge is down."""
    amount = Decimal(str(payload["amount"]))
    bank_timestamp = datetime.fromisoformat(payload["bank_timestamp"])
    ref = payload.get("ref_number")
    note = payload.get("note", "manual entry")

    idem = sha256(f"manual|{bank_timestamp.isoformat()}|{amount}|{ref or ''}".encode()).hexdigest()
    event = Event(
        source="manual",
        event_type="deposit.manual",
        payload=payload,
        received_at=_now_bkk(),
        source_timestamp=bank_timestamp,
        idempotency_key=idem,
    )
    session.add(event)
    session.flush()
    bank_tx = BankTransaction(
        bank_timestamp=bank_timestamp,
        amount=amount,
        direction="in",
        sender="manual",
        ref_number=ref,
        raw_sms=note,
        idempotency_key=idem,
        raw_event_id=event.id,
    )
    session.add(bank_tx)
    session.commit()
    return {"status": "ok", "bank_transaction_id": bank_tx.id}
