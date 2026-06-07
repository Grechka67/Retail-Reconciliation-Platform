"""Auth dependency for privileged endpoints.

Any route that mutates data (everything under /admin and /ingest/admin) must
present a valid `X-API-Key` header. The key lives in settings.admin_api_key,
which config.py forces to be a strong, non-default value at startup.
"""
import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    """Reject any request without the admin API key. compare_digest avoids timing leaks."""
    expected = get_settings().admin_api_key
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
