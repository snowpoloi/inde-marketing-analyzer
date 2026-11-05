"""Keep the selected storefront photo order with each render."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_promotion_gallery"
down_revision = "0014_promotion_render"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("promotion_render_jobs", sa.Column(
        "photo_selections", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column("promotion_render_jobs", "photo_selections")
