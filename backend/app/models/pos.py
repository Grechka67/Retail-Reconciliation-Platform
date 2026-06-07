from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class PosTransaction(SQLModel, table=True):
    __tablename__ = "pos_transactions"

    receipt_id: str = Field(primary_key=True, max_length=128)
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    total: Decimal = Field(max_digits=12, decimal_places=2)
    cash_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    transfer_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    payment_method: str = Field(max_length=32)  # cash | transfer | mixed
    employee_id: Optional[int] = Field(default=None, foreign_key="employees.id", index=True)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id", index=True)
    void_status: str = Field(default="active", max_length=16)  # active | voided | refunded
    refund_of_id: Optional[str] = Field(default=None, max_length=128)
    discount_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    line_items: list[dict[str, Any]] = Field(sa_column=Column(JSONB, nullable=False))
    raw_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("events.id")),
    )
