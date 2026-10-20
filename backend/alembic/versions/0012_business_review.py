"""Persistent evidence, historical acquisition queue and review snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0012_business_review"
down_revision = "0011_supplier_catalog"
branch_labels = None
depends_on = None


def columns():
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    op.create_table("review_events", *columns(),
        sa.Column("source_key", sa.String(64), unique=True, nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(255)),
        sa.Column("object_id", sa.String(255)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("reference_url", sa.Text()),
        sa.Column("payload", pg.JSONB(), nullable=False))
    for field in ("source", "occurred_at", "object_id"):
        op.create_index(f"ix_review_events_{field}", "review_events", [field])
    op.create_table("review_jobs", *columns(),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("records", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("meta", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("provider", "kind", "date_from", "date_to", name="uq_review_job_window"))
    for field in ("provider", "status"):
        op.create_index(f"ix_review_jobs_{field}", "review_jobs", [field])
    op.create_table("review_reports", *columns(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("parameters", pg.JSONB(), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False))


def downgrade():
    for table in ("review_reports", "review_jobs", "review_events"):
        op.drop_table(table)
