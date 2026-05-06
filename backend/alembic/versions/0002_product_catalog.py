"""product catalog

Revision ID: 0002_product_catalog
Revises: 0001_initial_schema
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_product_catalog"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "product_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.String(length=120), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=500), nullable=True),
        sa.Column("category_path", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("price", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("sku", name="uq_product_catalog_sku"),
    )
    op.create_index("ix_product_catalog_sku", "product_catalog", ["sku"])
    op.create_index("ix_product_catalog_model", "product_catalog", ["model"])
    op.create_index("ix_product_catalog_product_id", "product_catalog", ["product_id"])
    op.create_index("ix_product_catalog_brand_category", "product_catalog", ["brand", "category"])


def downgrade() -> None:
    op.drop_index("ix_product_catalog_brand_category", table_name="product_catalog")
    op.drop_index("ix_product_catalog_product_id", table_name="product_catalog")
    op.drop_index("ix_product_catalog_model", table_name="product_catalog")
    op.drop_index("ix_product_catalog_sku", table_name="product_catalog")
    op.drop_table("product_catalog")
