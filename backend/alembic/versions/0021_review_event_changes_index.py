"""Index the change history so a 93-day window is grouped from the index alone.

The nightly Google Ads feed upload adds thousands of change events per night. The change-history page groups them
per day, source, actor, type and title. With these columns in one index, PostgreSQL reads the index instead of
the wide event rows (their payload holds the full changed resource).
"""
from alembic import op

revision = "0021_review_event_changes_index"
down_revision = "0020_advestiq_proposals"
branch_labels = None
depends_on = None


def upgrade():
    # A B-tree entry must stay under ~2.7 kB. Titles and actors from Google and Meta are short; this only trims
    # hand-typed evidence long enough to break the index (none is expected). New rows are trimmed by store_event.
    op.execute("UPDATE review_events SET title = left(title, 250) WHERE octet_length(title) > 1000")
    op.execute("UPDATE review_events SET actor = left(actor, 120) WHERE octet_length(actor) > 500")
    op.create_index("ix_review_events_changes", "review_events", ["occurred_at", "id"],
                    postgresql_include=["source", "actor", "evidence_type", "title"])


def downgrade():
    op.drop_index("ix_review_events_changes", table_name="review_events")
