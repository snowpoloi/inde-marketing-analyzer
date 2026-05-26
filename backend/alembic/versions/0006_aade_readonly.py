"""aade readonly documents

Revision ID: 0006_aade_readonly
Revises: 0005_search_console_metrics
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_aade_readonly"
down_revision = "0005_search_console_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aade_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_endpoint", sa.String(length=80), nullable=False),
        sa.Column("identity_key", sa.String(length=700), nullable=False),
        sa.Column("mark", sa.String(length=128), nullable=True),
        sa.Column("uid", sa.String(length=128), nullable=True),
        sa.Column("issuer_vat", sa.String(length=32), nullable=True),
        sa.Column("counterpart_vat", sa.String(length=32), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("document_direction", sa.String(length=32), nullable=False),
        sa.Column("invoice_type", sa.String(length=64), nullable=True),
        sa.Column("series", sa.String(length=64), nullable=True),
        sa.Column("aa", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("net_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("vat_amount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("gross_value", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cancelled_by_mark", sa.String(length=128), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("identity_key", name="uq_aade_documents_identity_key"),
    )
    op.create_index("ix_aade_documents_source_endpoint", "aade_documents", ["source_endpoint"])
    op.create_index("ix_aade_documents_identity_key", "aade_documents", ["identity_key"])
    op.create_index("ix_aade_documents_mark", "aade_documents", ["mark"])
    op.create_index("ix_aade_documents_uid", "aade_documents", ["uid"])
    op.create_index("ix_aade_documents_issuer_vat", "aade_documents", ["issuer_vat"])
    op.create_index("ix_aade_documents_counterpart_vat", "aade_documents", ["counterpart_vat"])
    op.create_index("ix_aade_documents_issue_date", "aade_documents", ["issue_date"])
    op.create_index("ix_aade_documents_document_direction", "aade_documents", ["document_direction"])

    op.create_table(
        "aade_summary_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("source_endpoint", sa.String(length=80), nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "metric_date",
            "source_endpoint",
            "metric_name",
            name="uq_aade_summary_metrics_day_source_name",
        ),
    )
    op.create_index("ix_aade_summary_metrics_metric_date", "aade_summary_metrics", ["metric_date"])
    op.create_index("ix_aade_summary_metrics_source_endpoint", "aade_summary_metrics", ["source_endpoint"])


def downgrade() -> None:
    op.drop_index("ix_aade_summary_metrics_source_endpoint", table_name="aade_summary_metrics")
    op.drop_index("ix_aade_summary_metrics_metric_date", table_name="aade_summary_metrics")
    op.drop_table("aade_summary_metrics")
    op.drop_index("ix_aade_documents_document_direction", table_name="aade_documents")
    op.drop_index("ix_aade_documents_issue_date", table_name="aade_documents")
    op.drop_index("ix_aade_documents_counterpart_vat", table_name="aade_documents")
    op.drop_index("ix_aade_documents_issuer_vat", table_name="aade_documents")
    op.drop_index("ix_aade_documents_uid", table_name="aade_documents")
    op.drop_index("ix_aade_documents_mark", table_name="aade_documents")
    op.drop_index("ix_aade_documents_identity_key", table_name="aade_documents")
    op.drop_index("ix_aade_documents_source_endpoint", table_name="aade_documents")
    op.drop_table("aade_documents")
