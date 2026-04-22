"""Add direct_messages table

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-05 00:00:00
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "direct_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sender_id", sa.String(36),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column(
            "recipient_id", sa.String(36),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dm_recipient_id", "direct_messages", ["recipient_id"])
    op.create_index("ix_dm_sender_id", "direct_messages", ["sender_id"])


def downgrade() -> None:
    op.drop_index("ix_dm_sender_id", "direct_messages")
    op.drop_index("ix_dm_recipient_id", "direct_messages")
    op.drop_table("direct_messages")
