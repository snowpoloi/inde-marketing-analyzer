"""bank transactions

Revision ID: 0007_bank_transactions
Revises: 0006_aade_readonly
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_bank_transactions"
down_revision = "0006_aade_readonly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_name", sa.String(length=120), nullable=False),
        sa.Column("account", sa.String(length=160), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("counterparty", sa.String(length=500), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("debit", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("credit", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("balance", sa.Numeric(14, 4), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_bank_transactions_source_key"),
    )
    for column in (
        "bank_name",
        "account",
        "transaction_date",
        "value_date",
        "counterparty",
        "reference",
        "category",
        "transaction_type",
        "source_key",
    ):
        op.create_index(f"ix_bank_transactions_{column}", "bank_transactions", [column])


def downgrade() -> None:
    op.drop_table("bank_transactions")
