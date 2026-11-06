"""Store ADVESTIQ proposals, the owner's status for each and the notes on them."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_advestiq_proposals"
down_revision = "0023_merchant_product_issues"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "advestiq_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("executor", sa.String(32), nullable=False),
        sa.Column("what", sa.Text(), nullable=False, server_default=""),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected", sa.Text(), nullable=False, server_default=""),
        sa.Column("rollback", sa.Text(), nullable=False, server_default=""),
        sa.Column("check_7_on", sa.Date()),
        sa.Column("check_14_on", sa.Date()),
        sa.Column("message_subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("message_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.Column("advestiq_status", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="discussion"),
        sa.Column("status_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_advestiq_proposal_code"),
    )
    op.create_index("ix_advestiq_proposals_status", "advestiq_proposals", ["status"])
    op.create_table(
        "advestiq_proposal_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("advestiq_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
    )
    op.create_index("ix_advestiq_proposal_notes_proposal_id", "advestiq_proposal_notes", ["proposal_id"])


def downgrade():
    op.drop_index("ix_advestiq_proposal_notes_proposal_id", table_name="advestiq_proposal_notes")
    op.drop_table("advestiq_proposal_notes")
    op.drop_index("ix_advestiq_proposals_status", table_name="advestiq_proposals")
    op.drop_table("advestiq_proposals")
