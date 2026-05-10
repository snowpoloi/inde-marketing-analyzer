"""redact tokens from sync errors

Revision ID: 0004_redact_sync_error_tokens
Revises: 0003_opencart_order_analytics
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004_redact_sync_error_tokens"
down_revision: Union[str, None] = "0003_opencart_order_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sync_runs
        SET error_message = regexp_replace(
            error_message,
            '(access_token=)[^&[:space:]''"<>]+',
            '\\1[redacted]',
            'gi'
        )
        WHERE error_message ILIKE '%access_token=%'
        """
    )


def downgrade() -> None:
    pass
