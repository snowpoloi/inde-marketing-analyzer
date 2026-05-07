"""opencart order analytics fields

Revision ID: 0003_opencart_order_analytics
Revises: 0002_product_catalog
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_opencart_order_analytics"
down_revision: Union[str, None] = "0002_product_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("opencart_orders", sa.Column("date_modified", sa.DateTime(timezone=True), nullable=True))
    op.add_column("opencart_orders", sa.Column("order_status_id", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("store_id", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("store_name", sa.String(length=255), nullable=True))
    op.add_column("opencart_orders", sa.Column("customer_id", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("customer_group_id", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("customer_group", sa.String(length=255), nullable=True))
    op.add_column("opencart_orders", sa.Column("sub_total", sa.Numeric(14, 4), server_default="0", nullable=False))
    op.add_column("opencart_orders", sa.Column("tax", sa.Numeric(14, 4), server_default="0", nullable=False))
    op.add_column("opencart_orders", sa.Column("payment_code", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_method", sa.String(length=255), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_title", sa.String(length=255), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_code", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("tracking_carrier", sa.String(length=160), nullable=True))
    op.add_column("opencart_orders", sa.Column("payment_country", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("payment_zone", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("payment_city", sa.String(length=160), nullable=True))
    op.add_column("opencart_orders", sa.Column("payment_postcode", sa.String(length=40), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_country", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_zone", sa.String(length=120), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_city", sa.String(length=160), nullable=True))
    op.add_column("opencart_orders", sa.Column("shipping_postcode", sa.String(length=40), nullable=True))
    op.add_column("opencart_orders", sa.Column("currency_code", sa.String(length=12), nullable=True))

    op.create_index("ix_opencart_orders_date_modified", "opencart_orders", ["date_modified"])
    op.create_index("ix_opencart_orders_status_id", "opencart_orders", ["order_status_id"])
    op.create_index("ix_opencart_orders_customer_group_id", "opencart_orders", ["customer_group_id"])
    op.create_index("ix_opencart_orders_customer_group", "opencart_orders", ["customer_group"])
    op.create_index("ix_opencart_orders_payment_code", "opencart_orders", ["payment_code"])
    op.create_index("ix_opencart_orders_shipping_code", "opencart_orders", ["shipping_code"])
    op.create_index("ix_opencart_orders_tracking_carrier", "opencart_orders", ["tracking_carrier"])
    op.create_index("ix_opencart_orders_shipping_zone_city", "opencart_orders", ["shipping_zone", "shipping_city"])

    op.create_table(
        "opencart_order_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_pk", postgresql.UUID(as_uuid=True), sa.ForeignKey("opencart_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(length=120), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_opencart_order_changes_order_id", "opencart_order_changes", ["order_id"])
    op.create_index("ix_opencart_order_changes_field_name", "opencart_order_changes", ["field_name"])
    op.create_index("ix_opencart_order_changes_source_modified", "opencart_order_changes", ["source_modified_at"])
    op.create_index("ix_opencart_order_changes_detected", "opencart_order_changes", ["detected_at"])


def downgrade() -> None:
    op.drop_index("ix_opencart_order_changes_detected", table_name="opencart_order_changes")
    op.drop_index("ix_opencart_order_changes_source_modified", table_name="opencart_order_changes")
    op.drop_index("ix_opencart_order_changes_field_name", table_name="opencart_order_changes")
    op.drop_index("ix_opencart_order_changes_order_id", table_name="opencart_order_changes")
    op.drop_table("opencart_order_changes")

    op.drop_index("ix_opencart_orders_shipping_zone_city", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_tracking_carrier", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_shipping_code", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_payment_code", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_customer_group", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_customer_group_id", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_status_id", table_name="opencart_orders")
    op.drop_index("ix_opencart_orders_date_modified", table_name="opencart_orders")

    op.drop_column("opencart_orders", "currency_code")
    op.drop_column("opencart_orders", "shipping_postcode")
    op.drop_column("opencart_orders", "shipping_city")
    op.drop_column("opencart_orders", "shipping_zone")
    op.drop_column("opencart_orders", "shipping_country")
    op.drop_column("opencart_orders", "payment_postcode")
    op.drop_column("opencart_orders", "payment_city")
    op.drop_column("opencart_orders", "payment_zone")
    op.drop_column("opencart_orders", "payment_country")
    op.drop_column("opencart_orders", "shipping_code")
    op.drop_column("opencart_orders", "tracking_carrier")
    op.drop_column("opencart_orders", "shipping_title")
    op.drop_column("opencart_orders", "shipping_method")
    op.drop_column("opencart_orders", "payment_code")
    op.drop_column("opencart_orders", "tax")
    op.drop_column("opencart_orders", "sub_total")
    op.drop_column("opencart_orders", "customer_group")
    op.drop_column("opencart_orders", "customer_group_id")
    op.drop_column("opencart_orders", "customer_id")
    op.drop_column("opencart_orders", "store_name")
    op.drop_column("opencart_orders", "store_id")
    op.drop_column("opencart_orders", "order_status_id")
    op.drop_column("opencart_orders", "date_modified")
