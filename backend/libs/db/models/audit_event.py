from typing import Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    market: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
