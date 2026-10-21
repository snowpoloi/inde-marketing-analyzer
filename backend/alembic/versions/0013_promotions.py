"""Product promotion briefs and privately stored video assets."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0013_promotions"
down_revision = "0012_business_review"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("promotion_campaigns",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("brief", pg.JSONB(), nullable=False), *timestamps())
    op.create_index("ix_promotion_campaigns_owner_id", "promotion_campaigns", ["owner_id"])
    op.create_table("promotion_assets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("campaign_id", pg.UUID(as_uuid=True), sa.ForeignKey("promotion_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("aspect_ratio", sa.String(8), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("review", pg.JSONB(), nullable=False), *timestamps())
    op.create_index("ix_promotion_assets_campaign_id", "promotion_assets", ["campaign_id"])


def downgrade():
    op.drop_table("promotion_assets")
    op.drop_table("promotion_campaigns")
