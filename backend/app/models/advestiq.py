from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
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


class AdvestiqProposal(TimestampMixin, Base):
    """A change ADVESTIQ proposes. ADVESTIQ writes the content; only the owner sets `status`."""

    __tablename__ = "advestiq_proposals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    executor: Mapped[str] = mapped_column(String(32), nullable=False)
    what: Mapped[str] = mapped_column(Text, nullable=False, default="")
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rollback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    check_7_on: Mapped[date | None] = mapped_column(Date)
    check_14_on: Mapped[date | None] = mapped_column(Date)
    message_subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    message_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_on: Mapped[date] = mapped_column(Date, nullable=False)
    advestiq_status: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discussion", index=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdvestiqProposalNote(Base):
    """A comment on a proposal. `status` is set when the note records a status change by the owner."""

    __tablename__ = "advestiq_proposal_notes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("advestiq_proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str | None] = mapped_column(String(32))
    # clock_timestamp() keeps notes written in one transaction in the order they were added.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("clock_timestamp()"))
