from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)):
    s = get_settings()
    try:
        session.exec(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    now = datetime.now(ZoneInfo(s.timezone))
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
        "timezone": s.timezone,
        "server_time": now.isoformat(),
    }
