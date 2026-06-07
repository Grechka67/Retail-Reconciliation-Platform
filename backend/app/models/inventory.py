from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlmodel import Field, SQLModel


class InventoryItem(SQLModel, table=True):
    __tablename__ = "inventory_items"

    sku: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=256)
    category: Optional[str] = Field(default=None, max_length=64)
    unit: str = Field(default="piece", max_length=16)  # g | piece | bottle
    loyverse_item_id: Optional[str] = Field(default=None, max_length=64, unique=True)
    active: bool = Field(default=True)
    cost_thb: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    price_thb: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)


class InventoryMovement(SQLModel, table=True):
    __tablename__ = "inventory_movements"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    sku: str = Field(foreign_key="inventory_items.sku", max_length=64, index=True)
    movement_type: str = Field(max_length=32)  # received | sold | damaged | adjusted | opening
    quantity: Decimal = Field(max_digits=12, decimal_places=3)
    reference_id: Optional[str] = Field(default=None, max_length=128)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id")
    raw_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("events.id")),
    )


class InventoryCount(SQLModel, table=True):
    __tablename__ = "inventory_counts"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    shift_id: int = Field(foreign_key="shifts.id")
    sku: str = Field(foreign_key="inventory_items.sku", max_length=64)
    count_type: str = Field(max_length=16)  # opening | closing
    counted_value_1: Decimal = Field(max_digits=12, decimal_places=3)
    counted_value_2: Decimal = Field(max_digits=12, decimal_places=3)
    final_value: Decimal = Field(max_digits=12, decimal_places=3)
    counted_by: Optional[int] = Field(default=None, foreign_key="employees.id")
    counted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ShiftSalesReport(SQLModel, table=True):
    __tablename__ = "shift_sales_reports"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    shift_id: int = Field(foreign_key="shifts.id")
    employee_id: int = Field(foreign_key="employees.id")
    sku: str = Field(foreign_key="inventory_items.sku", max_length=64)
    reported_quantity: Decimal = Field(max_digits=12, decimal_places=3)
    reported_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    notes: Optional[str] = None
