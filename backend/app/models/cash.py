from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class CashSession(SQLModel, table=True):
    __tablename__ = "cash_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    shift_id: int = Field(foreign_key="shifts.id", unique=True)
    opening_amount: Decimal = Field(max_digits=12, decimal_places=2)
    expected_close: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    counted_close_1: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    counted_close_2: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    final_count: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    discrepancy: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    status: str = Field(default="open", max_length=32)
    opened_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    closed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True)),
    )
