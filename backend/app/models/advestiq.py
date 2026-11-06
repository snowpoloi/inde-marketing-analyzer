from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Date, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities import Base, TimestampMixin


class AdvestiqReport(TimestampMixin, Base):
    """A report written by ADVESTIQ (daily brief or weekly review), one per kind and date."""

    __tablename__ = "advestiq_reports"
    __table_args__ = (UniqueConstraint("kind", "report_date", name="uq_advestiq_report_kind_date"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
