from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlmodel import Field, SQLModel


class Employee(SQLModel, table=True):
    __tablename__ = "employees"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=128)
    loyverse_employee_id: Optional[str] = Field(default=None, max_length=64, unique=True)
    neocall_id: Optional[str] = Field(default=None, max_length=64, unique=True)
    active: bool = Field(default=True)
    role: str = Field(default="cashier", max_length=64)


class AttendanceLog(SQLModel, table=True):
    __tablename__ = "attendance_logs"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    employee_id: int = Field(foreign_key="employees.id")
    fingerprint_timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    event_type: str = Field(max_length=32)  # check_in | check_out
    raw_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("events.id")),
    )
