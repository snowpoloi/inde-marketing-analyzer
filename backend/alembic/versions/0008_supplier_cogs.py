"""supplier COGS and logistics ledgers

Revision ID: 0008_supplier_cogs
Revises: 0007_bank_transactions
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_supplier_cogs"
down_revision = "0007_bank_transactions"
branch_labels = None
depends_on = None


JSONB_DEFAULT = sa.text("'{}'::jsonb")
LIST_DEFAULT = sa.text("'[]'::jsonb")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    for column in ("line_subtotal", "discount", "tax", "total"):
        op.add_column(
            "opencart_order_products",
            sa.Column(column, sa.Numeric(14, 4), server_default="0", nullable=False),
        )
    for column, length in (("ean", 64), ("upc", 64), ("mpn", 160)):
        op.add_column("product_catalog", sa.Column(column, sa.String(length=length), nullable=True))
        op.create_index(f"ix_product_catalog_{column}", "product_catalog", [column])
        op.execute(sa.text(f"UPDATE product_catalog SET {column} = left(NULLIF(raw->>'{column}', ''), {length}) WHERE {column} IS NULL"))

    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vat_number", sa.String(length=32), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), server_default=LIST_DEFAULT, nullable=False),
        sa.Column("default_currency", sa.String(length=8), server_default="EUR", nullable=False),
        sa.Column("free_shipping_threshold", sa.Numeric(14, 4), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("code", name="uq_suppliers_code"),
    )
    _indexes("suppliers", ("code", "name", "vat_number"))

    op.create_table(
        "supplier_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="SET NULL")),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("imported_documents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("content_hash", name="uq_supplier_import_batches_content_hash"),
    )
    _indexes("supplier_import_batches", ("supplier_id", "source_type", "content_hash", "status"))

    op.create_table(
        "supplier_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_import_batches.id", ondelete="SET NULL")),
        sa.Column("aade_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("aade_documents.id", ondelete="SET NULL")),
        sa.Column("identity_key", sa.String(length=700), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("document_number", sa.String(length=160), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("supplier_order_id", sa.String(length=160), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="EUR", nullable=False),
        sa.Column("net_products_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("net_shipping_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("net_other_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("vat_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("gross_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("identity_key", name="uq_supplier_documents_identity_key"),
    )
    _indexes(
        "supplier_documents",
        (
            "supplier_id",
            "import_batch_id",
            "aade_document_id",
            "identity_key",
            "document_type",
            "document_number",
            "document_date",
            "supplier_order_id",
        ),
    )

    op.create_table(
        "supplier_product_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_catalog_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_catalog.id", ondelete="SET NULL")),
        sa.Column("identity_key", sa.String(length=700), nullable=False),
        sa.Column("supplier_code", sa.String(length=255), nullable=True),
        sa.Column("supplier_sku", sa.String(length=255), nullable=True),
        sa.Column("supplier_ean", sa.String(length=64), nullable=True),
        sa.Column("opencart_product_id", sa.String(length=120), nullable=True),
        sa.Column("opencart_sku", sa.String(length=255), nullable=True),
        sa.Column("opencart_model", sa.String(length=255), nullable=True),
        sa.Column("product_name", sa.String(length=500), nullable=True),
        sa.Column("purchase_unit", sa.String(length=32), nullable=True),
        sa.Column("sales_unit", sa.String(length=32), nullable=True),
        sa.Column("pack_quantity", sa.Numeric(14, 4), server_default="1", nullable=False),
        sa.Column("conversion_factor", sa.Numeric(14, 6), server_default="1", nullable=False),
        sa.Column("match_method", sa.String(length=64), server_default="unmatched", nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="unmatched", nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("supplier_id", "identity_key", name="uq_supplier_product_maps_supplier_identity"),
    )
    _indexes(
        "supplier_product_maps",
        (
            "supplier_id",
            "product_catalog_id",
            "supplier_code",
            "supplier_sku",
            "supplier_ean",
            "opencart_product_id",
            "opencart_sku",
            "opencart_model",
            "match_method",
            "status",
            "verified",
        ),
    )

    op.create_table(
        "supplier_document_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_product_map_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_product_maps.id", ondelete="SET NULL")),
        sa.Column("line_number", sa.String(length=64), nullable=False),
        sa.Column("line_type", sa.String(length=32), server_default="product", nullable=False),
        sa.Column("supplier_code", sa.String(length=255), nullable=True),
        sa.Column("supplier_sku", sa.String(length=255), nullable=True),
        sa.Column("supplier_ean", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("unit_price_before_discount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("discount_percent", sa.Numeric(8, 4), server_default="0", nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("net_unit_cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("net_line_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("vat_rate", sa.Numeric(8, 4), server_default="0", nullable=False),
        sa.Column("vat_amount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("gross_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("document_id", "line_number", name="uq_supplier_document_lines_number"),
    )
    _indexes("supplier_document_lines", ("document_id", "supplier_product_map_id", "line_type"))

    op.create_table(
        "supplier_product_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("supplier_product_map_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_product_maps.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_catalog_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_document_lines.id", ondelete="SET NULL")),
        sa.Column("supplier_sku", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("source_key", sa.String(length=700), nullable=False),
        sa.Column("supplier_order_id", sa.String(length=160), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=160), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("unit_price_before_discount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("discount_percent", sa.Numeric(8, 4), server_default="0", nullable=False),
        sa.Column("net_unit_cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("net_line_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("vat", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("gross_total", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="EUR", nullable=False),
        sa.Column("source_confidence", sa.Numeric(5, 4), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("source_key", name="uq_supplier_product_costs_source_key"),
    )
    _indexes(
        "supplier_product_costs",
        (
            "supplier_id",
            "supplier_product_map_id",
            "product_catalog_id",
            "source_line_id",
            "supplier_sku",
            "source_type",
            "source_key",
            "purchase_date",
            "status",
        ),
    )

    op.create_table(
        "supplier_shipping_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_documents.id", ondelete="SET NULL")),
        sa.Column("source_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_document_lines.id", ondelete="SET NULL")),
        sa.Column("source_key", sa.String(length=700), nullable=False),
        sa.Column("supplier_order_id", sa.String(length=160), nullable=True),
        sa.Column("invoice_reference", sa.String(length=160), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shipping_type", sa.String(length=32), server_default="INBOUND", nullable=False),
        sa.Column("net_shipping_cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("vat", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("gross_shipping_cost", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("order_net_purchase_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("cbm", sa.Numeric(14, 4), nullable=True),
        sa.Column("weight", sa.Numeric(14, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_DEFAULT, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("source_key", name="uq_supplier_shipping_costs_source_key"),
    )
    _indexes(
        "supplier_shipping_costs",
        ("supplier_id", "document_id", "source_key", "date", "shipping_type"),
    )


def downgrade() -> None:
    op.drop_table("supplier_shipping_costs")
    op.drop_table("supplier_product_costs")
    op.drop_table("supplier_document_lines")
    op.drop_table("supplier_product_maps")
    op.drop_table("supplier_documents")
    op.drop_table("supplier_import_batches")
    op.drop_table("suppliers")

    for column in ("mpn", "upc", "ean"):
        op.drop_index(f"ix_product_catalog_{column}", table_name="product_catalog")
        op.drop_column("product_catalog", column)
    for column in ("total", "tax", "discount", "line_subtotal"):
        op.drop_column("opencart_order_products", column)
