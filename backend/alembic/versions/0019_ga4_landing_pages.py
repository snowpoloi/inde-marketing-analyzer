"""Store the top GA4 landing pages per day and channel group."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_ga4_landing_pages"
down_revision = "0018_ga4_funnel_daily"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ga4_landing_page_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("landing_page", sa.String(1000), nullable=False),
        sa.Column("channel_group", sa.String(160), nullable=False),
        sa.Column("sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("engaged_sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("add_to_carts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("purchases", sa.Integer(), server_default="0", nullable=False),
        sa.Column("purchase_revenue", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Starts with metric_date, so it also serves the date-range reads.
        sa.UniqueConstraint("metric_date", "landing_page", "channel_group", name="uq_ga4_landing_page_daily_key"),
    )


def downgrade():
    op.drop_table("ga4_landing_page_daily_metrics")
