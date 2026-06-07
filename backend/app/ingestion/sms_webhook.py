"""Periodic check that the KBank SMS bridge is still alive."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.models import Alert, SmsBridgeHeartbeat

log = logging.getLogger("ot.sms_heartbeat")
BKK = ZoneInfo("Asia/Bangkok")


def check_sms_bridge_heartbeat() -> None:
    s = get_settings()
    now = datetime.now(BKK)
    deadline = now - timedelta(seconds=s.sms_bridge_heartbeat_timeout_seconds)

    with session_scope() as session:
        latest = session.exec(
            select(SmsBridgeHeartbeat).order_by(SmsBridgeHeartbeat.received_at.desc())
        ).first()

        if latest is None:
            return  # bridge has never reported — silent on first boot

        if latest.received_at < deadline:
            existing_alert = session.exec(
                select(Alert)
                .where(Alert.alert_type == "SMS_BRIDGE_DOWN")
                .where(Alert.acked_at.is_(None))
            ).first()
            if existing_alert:
                return
            session.add(Alert(
                severity="CRITICAL",
                alert_type="SMS_BRIDGE_DOWN",
                payload={
                    "last_heartbeat": latest.received_at.isoformat(),
                    "silence_minutes": int((now - latest.received_at).total_seconds() // 60),
                    "bridge_id": latest.bridge_id,
                },
                created_at=now,
            ))
            log.warning("SMS bridge silent since %s — alert raised", latest.received_at)
