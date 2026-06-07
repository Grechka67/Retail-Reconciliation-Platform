"""LINE Notify integration — primary alert channel (Thai team uses LINE).

Generate a token at https://notify-bot.line.me/my/ and set LINE_NOTIFY_TOKEN.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger("ot.alerts.line")
LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"


def send_line(message: str) -> bool:
    s = get_settings()
    if not s.line_notify_token:
        log.debug("LINE_NOTIFY_TOKEN not set — would have sent: %s", message[:120])
        return False
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                LINE_NOTIFY_URL,
                headers={"Authorization": f"Bearer {s.line_notify_token}"},
                data={"message": message},
            )
            r.raise_for_status()
            return True
    except Exception as e:
        log.warning("LINE Notify failed: %s", e)
        return False


def format_alert(severity: str, alert_type: str, payload: dict) -> str:
    icon = {"INFO": "•", "WARN": "⚠", "CRITICAL": "🚨"}.get(severity, "•")
    title_map = {
        "UNMATCHED_TRANSFER":     "Unmatched transfer",
        "POSSIBLE_DUPLICATE_TRANSFER": "Possible duplicate transfer",
        "CASH_DISCREPANCY":       "Cash drawer discrepancy",
        "INVENTORY_SHRINKAGE":    "Inventory shrinkage",
        "VOID_BURST":             "Repeated voids",
        "REFUND_SPIKE":           "Refund spike",
        "EXCESSIVE_DISCOUNT":     "Excessive discount",
        "SMS_BRIDGE_DOWN":        "KBank SMS bridge offline",
    }
    title = title_map.get(alert_type, alert_type)
    lines = [f"{icon} [{severity}] {title}"]
    for k, v in payload.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
