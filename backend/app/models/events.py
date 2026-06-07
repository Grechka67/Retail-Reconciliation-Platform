from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Event(SQLModel, table=True):
    """Append-only audit log. Every ingested fact lands here first.

    Updates and deletes are blocked by a database trigger — corrections
    create a new event with `corrects_event_id` pointing to the original.
    """

    __tablename__ = "events"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    source: str = Field(max_length=64, index=True)
    event_type: str = Field(max_length=128)
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    received_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    source_timestamp: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )
    source_id: Optional[str] = Field(default=None, max_length=256)
    idempotency_key: str = Field(max_length=256, unique=True, index=True)
    corrects_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("events.id"), nullable=True),
    )
