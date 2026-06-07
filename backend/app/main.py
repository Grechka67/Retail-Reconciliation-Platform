from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.config import get_settings
from app.api import health, ingestion, admin, dashboard
from app.scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ot")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("ShopOS backend starting up")
    start_scheduler()
    yield
    log.info("ShopOS backend shutting down")
    shutdown_scheduler()


app = FastAPI(
    title="ShopOS — Retail Operations Platform",
    description="Unifies a small store's POS, bank, cash, stock and staff data into one source of truth, with automatic reconciliation and anomaly alerts.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(ingestion.router, prefix="/ingest", tags=["ingestion"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/")
def root():
    return {
        "name": "ShopOS",
        "version": app.version,
        "timezone": get_settings().timezone,
        "docs": "/docs",
    }
