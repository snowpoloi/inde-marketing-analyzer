from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities import Base, TimestampMixin


class PromotionCampaign(TimestampMixin, Base):
    __tablename__ = "promotion_campaigns"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    brief: Mapped[dict] = mapped_column(JSONB)


class PromotionAsset(TimestampMixin, Base):
    __tablename__ = "promotion_assets"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("promotion_campaigns.id", ondelete="CASCADE"), index=True)
    aspect_ratio: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="needs_review")
    review: Mapped[dict] = mapped_column(JSONB, default=dict)
