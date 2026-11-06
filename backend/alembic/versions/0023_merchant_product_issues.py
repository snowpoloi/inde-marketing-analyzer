"""Store the latest Merchant Center approval status per product and destination, and item-level issues."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_merchant_product_issues"
down_revision = "0022_google_ads_asset_groups"
branch_labels = None
depends_on = None


def product_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("offer_id", sa.String(160), nullable=False),
        sa.Column("feed_label", sa.String(64), nullable=False),
        sa.Column("content_language", sa.String(16), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
    ]


def timestamps():
    return [
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "merchant_product_statuses",
        *product_columns(),
        sa.Column("reporting_context", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("approved_countries", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pending_countries", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("disapproved_countries", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status_since", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("offer_id", "feed_label", "content_language", "reporting_context",
                            name="uq_merchant_product_status_key"),
    )
    op.create_table(
        "merchant_product_issues",
        *product_columns(),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("resolution", sa.String(64), nullable=True),
        sa.Column("attribute", sa.String(160), nullable=False),
        sa.Column("reporting_context", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("documentation", sa.Text(), nullable=True),
        sa.Column("applicable_countries", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("offer_id", "feed_label", "content_language", "code", "reporting_context", "attribute",
                            name="uq_merchant_product_issue_key"),
    )


def downgrade():
    op.drop_table("merchant_product_issues")
    op.drop_table("merchant_product_statuses")
