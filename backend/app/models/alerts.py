from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    severity: str = Field(max_length=16, index=True)  # INFO | WARN | CRITICAL
    alert_type: str = Field(max_length=64)
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    financial_impact_thb: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    delivered_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True)),
    )
    acked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True)),
    )
    acked_by: Optional[int] = Field(default=None, foreign_key="employees.id")
    line_message_id: Optional[str] = Field(default=None, max_length=128)


class Discrepancy(SQLModel, table=True):
    __tablename__ = "discrepancies"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    discrepancy_type: str = Field(max_length=64)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id")
    employee_id: Optional[int] = Field(default=None, foreign_key="employees.id")
    sku: Optional[str] = Field(default=None, max_length=64)
    expected: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    actual: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    delta: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    detected_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    resolved: bool = Field(default=False)
    resolution_notes: Optional[str] = None
