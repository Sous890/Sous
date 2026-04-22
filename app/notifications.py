"""
Notification helpers.

Stage B: unread task comment counts.
Stage C: unread DM counts.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import DirectMessage, Task, TaskComment, TaskView, User


def unread_task_count(user: User, db: Session) -> int:
    """
    Count of tasks (visible to this user) that have comments newer than
    the user's last_seen_at, or that have comments and no view row at all.

    Admin sees all tasks. Worker sees only tasks assigned to them.
    """
    if user is None:
        return 0

    # Subquery: latest comment time per task
    latest_comment = (
        db.query(
            TaskComment.task_id,
            func.max(TaskComment.created_at).label("latest_at"),
        )
        .group_by(TaskComment.task_id)
        .subquery()
    )

    # Base task query filtered by visibility
    task_q = db.query(Task.id)
    if user.role != "admin":
        task_q = task_q.filter(Task.assignee_id == user.id)

    visible_task_ids = task_q.subquery()

    # Count tasks where latest comment > last_seen_at (or no view row)
    count = (
        db.query(func.count())
        .select_from(latest_comment)
        .join(visible_task_ids, latest_comment.c.task_id == visible_task_ids.c.id)
        .outerjoin(
            TaskView,
            and_(
                TaskView.task_id == latest_comment.c.task_id,
                TaskView.user_id == user.id,
            ),
        )
        .filter(
            or_(
                TaskView.last_seen_at == None,                          # never visited
                TaskView.last_seen_at < latest_comment.c.latest_at,    # visited but stale
            )
        )
        .scalar()
    )
    return count or 0


def unread_dm_count(user: User, db: Session) -> int:
    """Count of DMs where recipient=user and read_at IS NULL."""
    if user is None:
        return 0
    count = (
        db.query(func.count())
        .select_from(DirectMessage)
        .filter(
            DirectMessage.recipient_id == user.id,
            DirectMessage.read_at == None,  # noqa: E711
        )
        .scalar()
    )
    return count or 0
