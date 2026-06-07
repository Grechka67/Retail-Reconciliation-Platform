from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that must never make it to production — the app refuses to start on any of these.
_INSECURE = {"", "dev_secret_change_me", "changeme", "change_me", "dev_metabase_key_change_me_32chars"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ot_admin:changeme_local_only@postgres:5432/project_ot"
    timezone: str = "Asia/Bangkok"

    loyverse_api_token: str = ""
    loyverse_poll_interval_seconds: int = 60

    # Required secrets — no usable default. See .env.example for how to generate them.
    kbank_sms_hmac_secret: str = ""   # signs the KBank SMS bridge → /ingest/kbank/sms
    admin_api_key: str = ""           # guards every /admin/* and /ingest/admin/* endpoint

    line_notify_token: str = ""

    transfer_match_window_seconds: int = 600
    anomaly_cash_threshold_thb: float = 300.0
    inventory_shrinkage_alert_pct: float = 5.0
    sms_bridge_heartbeat_timeout_seconds: int = 900

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _require_secure_secrets(self):
        for name in ("kbank_sms_hmac_secret", "admin_api_key"):
            if getattr(self, name) in _INSECURE:
                raise ValueError(
                    f"{name.upper()} is unset or using an insecure default. "
                    "Set a strong, unique value in .env "
                    '(generate with: python -c "import secrets; print(secrets.token_urlsafe(32))").'
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
