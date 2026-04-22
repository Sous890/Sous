"""Add tasks table

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("assignee_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="assigned"),
        # timer_id and note_id reserved for Weekend 3 — stored as plain text UUIDs for now
        # (the timers/notes tables don't exist in the DB yet)
        sa.Column("timer_id", sa.String(36), nullable=True),
        sa.Column("note_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tasks_status", "tasks")
    op.drop_index("ix_tasks_assignee_id", "tasks")
    op.drop_table("tasks")
