"""Store GA4 purchase-funnel events per day, device category and channel group."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_ga4_funnel_daily"
down_revision = "0017_advestiq_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ga4_funnel_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("device_category", sa.String(40), nullable=False),
        sa.Column("channel_group", sa.String(160), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Starts with metric_date, so it also serves the date-range reads.
        sa.UniqueConstraint("metric_date", "event_name", "device_category", "channel_group", name="uq_ga4_funnel_daily_key"),
    )


def downgrade():
    op.drop_table("ga4_funnel_daily_metrics")
