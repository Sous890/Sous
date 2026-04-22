"""Add notes and timers tables

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-06 00:00:00
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "name", name="uq_notes_owner_name"),
    )
    op.create_index("ix_notes_owner_id", "notes", ["owner_id"])

    op.create_table(
        "timers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("fires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fired", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("cancelled", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_timers_owner_id", "timers", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_timers_owner_id", "timers")
    op.drop_table("timers")
    op.drop_index("ix_notes_owner_id", "notes")
    op.drop_table("notes")
