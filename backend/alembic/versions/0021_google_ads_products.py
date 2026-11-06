"""Store the costliest Google Ads product rows per day and campaign (Shopping and Performance Max)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_google_ads_products"
down_revision = "0020_google_ads_search_terms"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_ads_product_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(64), nullable=False),
        sa.Column("campaign_name", sa.String(255), nullable=False),
        sa.Column("campaign_type", sa.String(40), nullable=True),
        sa.Column("item_id", sa.String(160), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        *[sa.Column(f"custom_label_{index}", sa.String(255), nullable=True) for index in range(5)],
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversions", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversion_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Starts with metric_date, so it also serves the date-range reads.
        sa.UniqueConstraint("metric_date", "campaign_id", "item_id", name="uq_google_ads_product_daily_key"),
    )


def downgrade():
    op.drop_table("google_ads_product_daily_metrics")
