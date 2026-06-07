from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class SmsBridgeHeartbeat(SQLModel, table=True):
    __tablename__ = "sms_bridge_heartbeats"

    id: Optional[int] = Field(default=None, primary_key=True)
    received_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    bridge_id: str = Field(max_length=64)
    battery_pct: Optional[int] = None
    network_type: Optional[str] = Field(default=None, max_length=16)
