"""Separate supplier XML catalog; no financial or shop changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_supplier_catalog"
down_revision = "0010_supplier_gmail_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("supplier_catalog_feeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("adapter", sa.String(32), nullable=False),
        sa.Column("encrypted_url", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("refresh_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("supplier_catalog_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_catalog_feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_code", sa.String(255), nullable=False),
        sa.Column("supplier_sku", sa.String(255)),
        sa.Column("ean", sa.String(64)),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("category", sa.String(1000)),
        sa.Column("image_url", sa.Text()),
        sa.Column("quantity", sa.Integer()),
        sa.Column("wholesale_price_net", sa.Numeric(14, 4)),
        sa.Column("retail_price_gross", sa.Numeric(14, 4)),
        sa.Column("product_catalog_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_catalog.id", ondelete="SET NULL")),
        sa.Column("match_method", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("feed_id", "supplier_code", name="uq_supplier_catalog_product_identity"),
    )
    for column in ("feed_id", "supplier_code", "supplier_sku", "ean", "product_catalog_id"):
        op.create_index(f"ix_supplier_catalog_products_{column}", "supplier_catalog_products", [column])


def downgrade():
    op.drop_table("supplier_catalog_products")
    op.drop_table("supplier_catalog_feeds")
