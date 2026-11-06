"""Store ADVESTIQ reports and backfill Meta clicks from link clicks."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_advestiq_reports"
down_revision = "0016_promotion_soundtrack"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "advestiq_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "report_date", name="uq_advestiq_report_kind_date"),
    )
    op.create_index("ix_advestiq_reports_report_date", "advestiq_reports", ["report_date"])
    # Meta rows stored link clicks but left `clicks` at 0, so every report showed 0 Meta clicks.
    op.execute("UPDATE campaign_daily_metrics SET clicks = link_clicks WHERE source = 'meta_ads' AND clicks = 0 AND link_clicks > 0")


def downgrade():
    op.drop_index("ix_advestiq_reports_report_date", table_name="advestiq_reports")
    op.drop_table("advestiq_reports")
