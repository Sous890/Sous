"""
Agent tool definitions (schemas) and implementations.

Each implementation takes (user, db, **kwargs) and re-checks permissions
internally. tools_for() filters what the model sees, but tool functions
never trust the caller — defense in depth.

On permission failure: return {"error": "..."} — never raise inside a tool.
The model reads the error and explains it to the user.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import DirectMessage, Task, TaskComment, User, TASK_STATUSES
from app.permissions import CAPABILITIES

# ---------------------------------------------------------------------------
# Tool schemas (what the model sees)
# ---------------------------------------------------------------------------

LIST_MY_TASKS_TOOL = {
    "name": "list_my_tasks",
    "description": (
        "List all tasks currently assigned to you. Returns title, status, "
        "description, and task ID for each."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

LIST_ALL_TASKS_TOOL = {
    "name": "list_all_tasks",
    "description": (
        "List all tasks in the system across all workers. Includes assignee "
        "nickname, title, status, and task ID."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

UPDATE_TASK_STATUS_TOOL = {
    "name": "update_task_status",
    "description": (
        "Change the status of a task. Valid statuses: assigned, in_progress, "
        "blocked, done. Workers can only update tasks assigned to them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task UUID."},
            "new_status": {
                "type": "string",
                "enum": ["assigned", "in_progress", "blocked", "done"],
            },
        },
        "required": ["task_id", "new_status"],
    },
}

ADD_COMMENT_TOOL = {
    "name": "add_comment",
    "description": (
        "Add a comment to a task. Workers can only comment on tasks assigned to them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task UUID."},
            "body": {"type": "string", "description": "The comment text."},
        },
        "required": ["task_id", "body"],
    },
}

CREATE_TASK_TOOL = {
    "name": "create_task",
    "description": (
        "Create a new task and assign it to a worker. Returns the new task ID. "
        "Admin only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string", "description": "Optional details."},
            "assignee_id": {
                "type": "string",
                "description": "UUID of the user to assign the task to.",
            },
        },
        "required": ["title", "assignee_id"],
    },
}

ASSIGN_TASK_TOOL = {
    "name": "assign_task",
    "description": "Reassign an existing task to a different user. Admin only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "new_assignee_id": {"type": "string", "description": "UUID of the new assignee."},
        },
        "required": ["task_id", "new_assignee_id"],
    },
}

SEND_DM_TOOL = {
    "name": "send_dm",
    "description": (
        "Send a direct message to another user. Workers can only message the "
        "coordinator (admin). Admin can message any worker."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "recipient_id": {"type": "string", "description": "UUID of the recipient."},
            "body": {"type": "string", "description": "Message text."},
        },
        "required": ["recipient_id", "body"],
    },
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def impl_list_my_tasks(user: User, db: Session, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("view_own_tasks"):
        return {"error": "Permission denied: you need view_own_tasks to list your tasks."}
    tasks = (
        db.query(Task)
        .filter(Task.assignee_id == user.id)
        .order_by(Task.created_at.desc())
        .all()
    )
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "description": t.description or "",
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


def impl_list_all_tasks(user: User, db: Session, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("view_others_tasks"):
        return {"error": "Permission denied: you need view_others_tasks to list all tasks."}
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "assignee": t.assignee.nickname if t.assignee else "unknown",
                "description": t.description or "",
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


def impl_update_task_status(user: User, db: Session, task_id: str, new_status: str, **kwargs) -> dict:
    if new_status not in TASK_STATUSES:
        return {"error": f"Invalid status '{new_status}'. Valid: {TASK_STATUSES}"}

    task = db.get(Task, task_id)
    if not task:
        return {"error": f"Task {task_id} not found."}

    if user.role != "admin":
        if not user.has_capability("update_own_tasks"):
            return {"error": "Permission denied: you need update_own_tasks."}
        if task.assignee_id != user.id:
            return {"error": "Permission denied: you can only update tasks assigned to you."}

    old_status = task.status
    task.status = new_status
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"updated": True, "task_id": task_id, "old_status": old_status, "new_status": new_status}


def impl_add_comment(user: User, db: Session, task_id: str, body: str, **kwargs) -> dict:
    body = body.strip()
    if not body:
        return {"error": "Comment body cannot be empty."}

    task = db.get(Task, task_id)
    if not task:
        return {"error": f"Task {task_id} not found."}

    if user.role != "admin":
        if not user.has_capability("comment_on_own_tasks"):
            return {"error": "Permission denied: you need comment_on_own_tasks."}
        if task.assignee_id != user.id:
            return {"error": "Permission denied: you can only comment on tasks assigned to you."}

    comment = TaskComment(task_id=task_id, author_id=user.id, body=body)
    db.add(comment)
    db.commit()
    return {"added": True, "task_id": task_id, "task_title": task.title}


def impl_create_task(user: User, db: Session, title: str, assignee_id: str, description: str = "", **kwargs) -> dict:
    if user.role != "admin":
        return {"error": "Permission denied: only admins can create tasks."}

    assignee = db.get(User, assignee_id)
    if not assignee:
        return {"error": f"User {assignee_id} not found."}

    task = Task(
        title=title.strip(),
        description=description.strip() or None,
        assignee_id=assignee_id,
        created_by_id=user.id,
        status="assigned",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"created": True, "task_id": task.id, "title": task.title, "assignee": assignee.nickname}


def impl_assign_task(user: User, db: Session, task_id: str, new_assignee_id: str, **kwargs) -> dict:
    if user.role != "admin":
        return {"error": "Permission denied: only admins can reassign tasks."}

    task = db.get(Task, task_id)
    if not task:
        return {"error": f"Task {task_id} not found."}

    new_assignee = db.get(User, new_assignee_id)
    if not new_assignee:
        return {"error": f"User {new_assignee_id} not found."}

    old_assignee = task.assignee.nickname if task.assignee else "unknown"
    task.assignee_id = new_assignee_id
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "reassigned": True,
        "task_id": task_id,
        "title": task.title,
        "from": old_assignee,
        "to": new_assignee.nickname,
    }


def impl_send_dm(user: User, db: Session, recipient_id: str, body: str, **kwargs) -> dict:
    body = body.strip()
    if not body:
        return {"error": "Message body cannot be empty."}

    recipient = db.get(User, recipient_id)
    if not recipient:
        return {"error": f"User {recipient_id} not found."}

    if user.role != "admin":
        if not user.has_capability("dm_coordinator"):
            return {"error": "Permission denied: you need dm_coordinator to send DMs."}
        if recipient.role != "admin":
            return {"error": "Permission denied: workers can only message the coordinator, not other workers."}

    msg = DirectMessage(sender_id=user.id, recipient_id=recipient_id, body=body)
    db.add(msg)
    db.commit()
    return {"sent": True, "to": recipient.nickname, "preview": body[:80]}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

IMPL_MAP = {
    "list_my_tasks": impl_list_my_tasks,
    "list_all_tasks": impl_list_all_tasks,
    "update_task_status": impl_update_task_status,
    "add_comment": impl_add_comment,
    "create_task": impl_create_task,
    "assign_task": impl_assign_task,
    "send_dm": impl_send_dm,
}


def dispatch(tool_name: str, tool_input: dict, user: User, db: Session) -> str:
    fn = IMPL_MAP.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = fn(user=user, db=db, **tool_input)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": f"Tool error: {str(e)}"})
