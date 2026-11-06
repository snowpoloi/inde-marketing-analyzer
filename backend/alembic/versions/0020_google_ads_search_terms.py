"""Store the costliest Google Ads search terms per day (Search, Shopping and Performance Max)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_google_ads_search_terms"
down_revision = "0019_ga4_landing_pages"
branch_labels = None
depends_on = None


def metric_columns():
    return [
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversions", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversion_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "google_ads_search_term_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(64), nullable=False),
        sa.Column("campaign_name", sa.String(255), nullable=False),
        sa.Column("campaign_type", sa.String(40), nullable=True),
        sa.Column("ad_group_id", sa.String(64), nullable=False),
        sa.Column("ad_group_name", sa.String(255), nullable=True),
        sa.Column("search_term", sa.String(500), nullable=False),
        sa.Column("match_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        *metric_columns(),
        # Starts with metric_date, so it also serves the date-range reads.
        sa.UniqueConstraint("metric_date", "campaign_id", "ad_group_id", "search_term", "match_type",
                            name="uq_google_ads_search_term_daily_key"),
    )


def downgrade():
    op.drop_table("google_ads_search_term_daily_metrics")
