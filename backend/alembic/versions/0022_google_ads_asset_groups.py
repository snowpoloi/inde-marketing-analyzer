"""Store Google Ads Performance Max results per asset group and day."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_google_ads_asset_groups"
down_revision = "0021_google_ads_products"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_ads_asset_group_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(64), nullable=False),
        sa.Column("campaign_name", sa.String(255), nullable=False),
        sa.Column("asset_group_id", sa.String(64), nullable=False),
        sa.Column("asset_group_name", sa.String(255), nullable=False),
        sa.Column("asset_group_status", sa.String(32), nullable=True),
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversions", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversion_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Starts with metric_date, so it also serves the date-range reads.
        sa.UniqueConstraint("metric_date", "asset_group_id", name="uq_google_ads_asset_group_daily_key"),
    )


def downgrade():
    op.drop_table("google_ads_asset_group_daily_metrics")
