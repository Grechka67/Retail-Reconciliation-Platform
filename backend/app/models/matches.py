from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlmodel import Field, SQLModel


class TransferMatch(SQLModel, table=True):
    __tablename__ = "transfer_matches"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    pos_transaction_id: str = Field(foreign_key="pos_transactions.receipt_id", unique=True, max_length=128)
    bank_transaction_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("bank_transactions.id")),
    )
    status: str = Field(max_length=32, index=True)  # VERIFIED | UNMATCHED | POSSIBLE_DUPLICATE
    confidence: Optional[Decimal] = Field(default=None, max_digits=3, decimal_places=2)
    time_delta_seconds: Optional[int] = None
    matched_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
