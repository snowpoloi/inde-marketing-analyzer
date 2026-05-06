"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "integration_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("provider", name="uq_integration_settings_provider"),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("sync_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_sync_runs_provider_started", "sync_runs", ["provider", "started_at"])

    op.create_table(
        "campaign_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(length=120), nullable=True),
        sa.Column("campaign_name", sa.String(length=255), nullable=False),
        sa.Column("campaign_type", sa.String(length=120), nullable=True),
        sa.Column("adset_id", sa.String(length=120), nullable=True),
        sa.Column("adset_name", sa.String(length=255), nullable=True),
        sa.Column("ad_id", sa.String(length=120), nullable=True),
        sa.Column("ad_name", sa.String(length=255), nullable=True),
        sa.Column("cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conversions", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversion_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("purchases", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("purchase_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("reach", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frequency", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("link_clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("landing_page_views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("add_to_cart", sa.Integer(), server_default="0", nullable=False),
        sa.Column("initiate_checkout", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cpc", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("cpm", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("ctr", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("avg_cpc", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("cost_per_conversion", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_campaign_metrics_source_date", "campaign_daily_metrics", ["source", "metric_date"])
    op.create_index("ix_campaign_metrics_campaign", "campaign_daily_metrics", ["source", "campaign_id"])

    op.create_table(
        "ga4_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("channel_group", sa.String(length=160), nullable=True),
        sa.Column("source_medium", sa.String(length=255), nullable=True),
        sa.Column("sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("purchases", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("purchase_revenue", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("conversions", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_ga4_metrics_date", "ga4_daily_metrics", ["metric_date"])

    op.create_table(
        "merchant_product_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("item_id", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=500), nullable=True),
        sa.Column("availability", sa.String(length=80), nullable=True),
        sa.Column("price", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("sale_price", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ctr", sa.Numeric(10, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_merchant_metrics_date_item", "merchant_product_metrics", ["metric_date", "item_id"])

    op.create_table(
        "opencart_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", sa.String(length=120), nullable=False),
        sa.Column("date_added", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_status", sa.String(length=120), nullable=True),
        sa.Column("total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("shipping", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("payment_method", sa.String(length=255), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("order_id", name="uq_opencart_orders_order_id"),
    )
    op.create_index("ix_opencart_orders_date", "opencart_orders", ["date_added"])

    op.create_table(
        "opencart_order_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_pk", postgresql.UUID(as_uuid=True), sa.ForeignKey("opencart_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=500), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("price", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_order_products_sku", "opencart_order_products", ["sku"])
    op.create_index("ix_order_products_brand_category", "opencart_order_products", ["brand", "category"])

    op.create_table(
        "shoply_sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_order_id", sa.String(length=160), nullable=True),
        sa.Column("sale_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_shoply_sales_date", "shoply_sales", ["sale_date"])

    op.create_table(
        "campaign_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recommendation_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=120), nullable=True),
        sa.Column("campaign_name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_recommendations_date_source", "campaign_recommendations", ["recommendation_date", "source"])


def downgrade() -> None:
    op.drop_index("ix_recommendations_date_source", table_name="campaign_recommendations")
    op.drop_table("campaign_recommendations")
    op.drop_index("ix_shoply_sales_date", table_name="shoply_sales")
    op.drop_table("shoply_sales")
    op.drop_index("ix_order_products_brand_category", table_name="opencart_order_products")
    op.drop_index("ix_order_products_sku", table_name="opencart_order_products")
    op.drop_table("opencart_order_products")
    op.drop_index("ix_opencart_orders_date", table_name="opencart_orders")
    op.drop_table("opencart_orders")
    op.drop_index("ix_merchant_metrics_date_item", table_name="merchant_product_metrics")
    op.drop_table("merchant_product_metrics")
    op.drop_index("ix_ga4_metrics_date", table_name="ga4_daily_metrics")
    op.drop_table("ga4_daily_metrics")
    op.drop_index("ix_campaign_metrics_campaign", table_name="campaign_daily_metrics")
    op.drop_index("ix_campaign_metrics_source_date", table_name="campaign_daily_metrics")
    op.drop_table("campaign_daily_metrics")
    op.drop_index("ix_sync_runs_provider_started", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("integration_settings")
    op.drop_table("users")

