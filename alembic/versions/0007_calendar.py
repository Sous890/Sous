"""Add calendar events, attendees, and task-tag join tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22 00:00:00
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("location", sa.Text, nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])

    op.create_table(
        "event_attendees",
        sa.Column(
            "event_id", sa.String(36),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "event_tasks",
        sa.Column(
            "event_id", sa.String(36),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column(
            "task_id", sa.String(36),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("event_tasks")
    op.drop_table("event_attendees")
    op.drop_index("ix_calendar_events_starts_at", "calendar_events")
    op.drop_table("calendar_events")
