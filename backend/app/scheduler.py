import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings

log = logging.getLogger("ot.scheduler")

_scheduler: BackgroundScheduler | None = None


def _safe(job):
    def wrapped():
        try:
            job()
        except Exception as e:
            log.exception("Job %s failed: %s", job.__name__, e)
    wrapped.__name__ = job.__name__
    return wrapped


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    from app.ingestion.loyverse import poll_loyverse_receipts
    from app.reconciliation.transfers import reconcile_transfers
    from app.reconciliation.cash import close_eligible_cash_sessions
    from app.anomaly.rules import scan_for_anomalies
    from app.ingestion.sms_webhook import check_sms_bridge_heartbeat

    s = get_settings()
    _scheduler = BackgroundScheduler(timezone=s.timezone)

    _scheduler.add_job(
        _safe(poll_loyverse_receipts),
        IntervalTrigger(seconds=s.loyverse_poll_interval_seconds),
        id="loyverse_poll",
        replace_existing=True,
    )
    _scheduler.add_job(
        _safe(reconcile_transfers),
        IntervalTrigger(minutes=5),
        id="reconcile_transfers",
        replace_existing=True,
    )
    _scheduler.add_job(
        _safe(close_eligible_cash_sessions),
        IntervalTrigger(minutes=10),
        id="cash_session_close",
        replace_existing=True,
    )
    _scheduler.add_job(
        _safe(scan_for_anomalies),
        IntervalTrigger(minutes=15),
        id="anomaly_scan",
        replace_existing=True,
    )
    _scheduler.add_job(
        _safe(check_sms_bridge_heartbeat),
        IntervalTrigger(minutes=5),
        id="sms_heartbeat",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("APScheduler started with %d jobs", len(_scheduler.get_jobs()))


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
