from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlmodel import Field, SQLModel


class BankTransaction(SQLModel, table=True):
    __tablename__ = "bank_transactions"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    bank_timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    amount: Decimal = Field(max_digits=12, decimal_places=2, index=True)
    direction: str = Field(max_length=8)  # in | out
    sender: Optional[str] = Field(default=None, max_length=64)
    ref_number: Optional[str] = Field(default=None, max_length=64)
    balance: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    raw_sms: Optional[str] = Field(default=None)
    idempotency_key: str = Field(max_length=256, unique=True)
    raw_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("events.id")),
    )
