"""Remember the music selected for each promotion render."""
import sqlalchemy as sa
from alembic import op

revision = "0016_promotion_soundtrack"
down_revision = "0015_promotion_gallery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("promotion_render_jobs", sa.Column("soundtrack_id", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("promotion_render_jobs", "soundtrack_id")
