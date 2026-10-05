"""Read-only Gmail supplier document staging.

Revision ID: 0009_supplier_gmail
Revises: 0008_supplier_cogs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_supplier_gmail"
down_revision = "0008_supplier_cogs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("supplier_gmail_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mailbox", sa.String(255), nullable=False),
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("part_id", sa.String(128), nullable=False),
        sa.Column("attachment_id", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("semantic_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("duplicate_of_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_gmail_sources.id", ondelete="SET NULL")),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier_import_batches.id", ondelete="SET NULL")),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_key", name="uq_supplier_gmail_sources_source_key"),
    )
    for column in ("content_hash", "semantic_hash", "status"):
        op.create_index(f"ix_supplier_gmail_sources_{column}", "supplier_gmail_sources", [column])


def downgrade():
    op.drop_table("supplier_gmail_sources")
