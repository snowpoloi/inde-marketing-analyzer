"""search console metrics

Revision ID: 0005_search_console_metrics
Revises: 0004_redact_sync_error_tokens
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_search_console_metrics"
down_revision = "0004_redact_sync_error_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_console_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("site_url", sa.String(length=500), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=True),
        sa.Column("page", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=16), nullable=True),
        sa.Column("device", sa.String(length=32), nullable=True),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ctr", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("position", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_search_console_daily_metrics_metric_date",
        "search_console_daily_metrics",
        ["metric_date"],
    )
    op.create_index("ix_search_console_daily_metrics_site_url", "search_console_daily_metrics", ["site_url"])
    op.create_index("ix_search_console_daily_metrics_query", "search_console_daily_metrics", ["query"])
    op.create_index("ix_search_console_daily_metrics_country", "search_console_daily_metrics", ["country"])
    op.create_index("ix_search_console_daily_metrics_device", "search_console_daily_metrics", ["device"])


def downgrade() -> None:
    op.drop_index("ix_search_console_daily_metrics_device", table_name="search_console_daily_metrics")
    op.drop_index("ix_search_console_daily_metrics_country", table_name="search_console_daily_metrics")
    op.drop_index("ix_search_console_daily_metrics_query", table_name="search_console_daily_metrics")
    op.drop_index("ix_search_console_daily_metrics_site_url", table_name="search_console_daily_metrics")
    op.drop_index("ix_search_console_daily_metrics_metric_date", table_name="search_console_daily_metrics")
    op.drop_table("search_console_daily_metrics")
