"""Queue local MP4 renders with confirmed INDE prices."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0014_promotion_render"
down_revision = "0013_promotions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("promotion_render_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("campaign_id", pg.UUID(as_uuid=True), sa.ForeignKey("promotion_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("aspect_ratio", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prices", pg.JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_promotion_render_jobs_campaign_id", "promotion_render_jobs", ["campaign_id"])
    op.create_index("ix_promotion_render_jobs_status", "promotion_render_jobs", ["status"])


def downgrade():
    op.drop_table("promotion_render_jobs")
