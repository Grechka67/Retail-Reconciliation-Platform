from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import ARRAY, INTEGER
from sqlmodel import Field, SQLModel


class Shift(SQLModel, table=True):
    __tablename__ = "shifts"

    id: Optional[int] = Field(default=None, primary_key=True)
    scheduled_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    scheduled_end: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    actual_start: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True)),
    )
    actual_end: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True)),
    )
    employee_ids: list[int] = Field(sa_column=Column(ARRAY(INTEGER), nullable=False))
    attendance_confidence: Decimal = Field(default=Decimal("1.00"), decimal_places=2, max_digits=3)
    status: str = Field(default="scheduled", max_length=32)
