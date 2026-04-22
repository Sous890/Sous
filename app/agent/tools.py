"""
Agent tool definitions (schemas) and implementations.

Each implementation takes (user, db, **kwargs) and re-checks permissions
internally. tools_for() filters what the model sees, but tool functions
never trust the caller — defense in depth.

On permission failure: return {"error": "..."} — never raise inside a tool.
The model reads the error and explains it to the user.
"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import DirectMessage, Note, Task, TaskComment, Timer, User, TASK_STATUSES
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

LIST_USERS_TOOL = {
    "name": "list_users",
    "description": (
        "List all active users in the system with their ID, username, nickname, and role. "
        "Useful when you need to find a user's ID for DMs, task assignment, or sending notes. "
        "Admin only."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

CREATE_NOTE_TOOL = {
    "name": "create_note",
    "description": (
        "Create a new personal note. Notes are private to you unless sent to someone. "
        "The name must be unique among your notes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short title / name for the note."},
            "body": {"type": "string", "description": "Note content."},
        },
        "required": ["name"],
    },
}

LIST_MY_NOTES_TOOL = {
    "name": "list_my_notes",
    "description": "List all your notes. Returns note IDs, names, and creation dates.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

READ_NOTE_TOOL = {
    "name": "read_note",
    "description": "Read the full body of one of your notes by its ID or name.",
    "input_schema": {
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "UUID of the note (preferred)."},
            "name": {"type": "string", "description": "Note name (used if note_id omitted)."},
        },
        "required": [],
    },
}

UPDATE_NOTE_TOOL = {
    "name": "update_note",
    "description": "Replace the body of an existing note. You can also rename it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "UUID of the note."},
            "body": {"type": "string", "description": "New body content."},
            "name": {"type": "string", "description": "New name (optional rename)."},
        },
        "required": ["note_id"],
    },
}

DELETE_NOTE_TOOL = {
    "name": "delete_note",
    "description": "Permanently delete one of your notes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "UUID of the note to delete."},
        },
        "required": ["note_id"],
    },
}

SEND_NOTE_TOOL = {
    "name": "send_note",
    "description": (
        "Send the contents of one of your notes to another user as a direct message. "
        "Workers can only send to the coordinator (admin). Admin can send to anyone."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "UUID of the note to send."},
            "recipient_id": {"type": "string", "description": "UUID of the recipient user."},
        },
        "required": ["note_id", "recipient_id"],
    },
}

START_TIMER_TOOL = {
    "name": "start_timer",
    "description": (
        "Start a countdown timer. Specify duration in minutes (or seconds). "
        "The timer tracks when it will fire server-side. You can check it with list_timers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "duration_minutes": {
                "type": "number",
                "description": "How long to count down in minutes.",
            },
            "label": {
                "type": "string",
                "description": "Optional label to remember what this timer is for.",
            },
        },
        "required": ["duration_minutes"],
    },
}

LIST_TIMERS_TOOL = {
    "name": "list_timers",
    "description": (
        "List your active (non-cancelled, non-fired) timers. "
        "Shows label, time remaining, and whether each has fired."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

CANCEL_TIMER_TOOL = {
    "name": "cancel_timer",
    "description": "Cancel an active timer so it no longer counts down.",
    "input_schema": {
        "type": "object",
        "properties": {
            "timer_id": {"type": "string", "description": "UUID of the timer to cancel."},
        },
        "required": ["timer_id"],
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
# New tool implementations
# ---------------------------------------------------------------------------

def impl_list_users(user: User, db: Session, **kwargs) -> dict:
    if user.role != "admin":
        return {"error": "Permission denied: only admins can list all users."}
    users = db.query(User).filter(User.is_active == True).order_by(User.nickname).all()
    return {
        "users": [
            {"id": u.id, "username": u.username, "nickname": u.nickname, "role": u.role}
            for u in users
        ],
        "count": len(users),
    }


def impl_create_note(user: User, db: Session, name: str, body: str = "", **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    name = name.strip()
    if not name:
        return {"error": "Note name cannot be empty."}
    existing = db.query(Note).filter(Note.owner_id == user.id, Note.name == name).first()
    if existing:
        return {"error": f"You already have a note named '{name}'. Choose a different name or update the existing one."}
    note = Note(owner_id=user.id, name=name, body=body.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"created": True, "note_id": note.id, "name": note.name}


def impl_list_my_notes(user: User, db: Session, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    notes = db.query(Note).filter(Note.owner_id == user.id).order_by(Note.updated_at.desc()).all()
    return {
        "notes": [
            {"id": n.id, "name": n.name, "updated_at": str(n.updated_at)}
            for n in notes
        ],
        "count": len(notes),
    }


def impl_read_note(user: User, db: Session, note_id: str = "", name: str = "", **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    if note_id:
        note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    elif name:
        note = db.query(Note).filter(Note.name == name.strip(), Note.owner_id == user.id).first()
    else:
        return {"error": "Provide note_id or name."}
    if not note:
        return {"error": "Note not found."}
    return {"note_id": note.id, "name": note.name, "body": note.body, "updated_at": str(note.updated_at)}


def impl_update_note(user: User, db: Session, note_id: str, body: str = None, name: str = None, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        return {"error": "Note not found."}
    if body is not None:
        note.body = body
    if name is not None:
        name = name.strip()
        if name:
            note.name = name
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"updated": True, "note_id": note.id, "name": note.name}


def impl_delete_note(user: User, db: Session, note_id: str, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        return {"error": "Note not found."}
    name = note.name
    db.delete(note)
    db.commit()
    return {"deleted": True, "note_id": note_id, "name": name}


def impl_send_note(user: User, db: Session, note_id: str, recipient_id: str, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("create_note"):
        return {"error": "Permission denied: you need create_note capability."}
    if user.role != "admin" and not user.has_capability("dm_coordinator"):
        return {"error": "Permission denied: you need dm_coordinator to send notes to others."}

    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        return {"error": "Note not found."}

    recipient = db.get(User, recipient_id)
    if not recipient:
        return {"error": f"Recipient {recipient_id} not found."}

    if user.role != "admin" and recipient.role != "admin":
        return {"error": "Permission denied: workers can only send to the coordinator."}

    body = f"📄 Note from {user.nickname}: **{note.name}**\n\n{note.body}"
    msg = DirectMessage(sender_id=user.id, recipient_id=recipient_id, body=body)
    db.add(msg)
    db.commit()
    return {"sent": True, "note_name": note.name, "to": recipient.nickname}


def impl_start_timer(user: User, db: Session, duration_minutes: float, label: str = "", **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("start_timer"):
        return {"error": "Permission denied: you need start_timer capability."}
    if duration_minutes <= 0:
        return {"error": "Duration must be greater than 0."}
    if duration_minutes > 1440:
        return {"error": "Duration cannot exceed 24 hours (1440 minutes)."}

    duration_seconds = int(duration_minutes * 60)
    now = datetime.now(timezone.utc)
    fires_at = now + timedelta(seconds=duration_seconds)

    timer = Timer(
        owner_id=user.id,
        label=label.strip() or None,
        duration_seconds=duration_seconds,
        started_at=now,
        fires_at=fires_at,
    )
    db.add(timer)
    db.commit()
    db.refresh(timer)
    return {
        "started": True,
        "timer_id": timer.id,
        "label": timer.label or "(no label)",
        "duration_minutes": duration_minutes,
        "fires_at": fires_at.strftime("%H:%M:%S UTC"),
    }


def impl_list_timers(user: User, db: Session, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("start_timer"):
        return {"error": "Permission denied: you need start_timer capability."}
    now = datetime.now(timezone.utc)
    timers = (
        db.query(Timer)
        .filter(Timer.owner_id == user.id, Timer.cancelled == False)
        .order_by(Timer.fires_at)
        .all()
    )
    result = []
    for t in timers:
        fires_at = t.fires_at
        if fires_at.tzinfo is None:
            fires_at = fires_at.replace(tzinfo=timezone.utc)
        remaining = (fires_at - now).total_seconds()
        result.append({
            "timer_id": t.id,
            "label": t.label or "(no label)",
            "fired": t.fired,
            "fires_at": fires_at.strftime("%H:%M:%S UTC"),
            "seconds_remaining": max(0, int(remaining)),
            "minutes_remaining": round(max(0, remaining) / 60, 1),
        })
    return {"timers": result, "count": len(result)}


def impl_cancel_timer(user: User, db: Session, timer_id: str, **kwargs) -> dict:
    if user.role != "admin" and not user.has_capability("start_timer"):
        return {"error": "Permission denied: you need start_timer capability."}
    timer = db.query(Timer).filter(Timer.id == timer_id, Timer.owner_id == user.id).first()
    if not timer:
        return {"error": "Timer not found."}
    if timer.cancelled:
        return {"error": "Timer is already cancelled."}
    timer.cancelled = True
    db.commit()
    return {"cancelled": True, "timer_id": timer_id, "label": timer.label or "(no label)"}


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
    "list_users": impl_list_users,
    "create_note": impl_create_note,
    "list_my_notes": impl_list_my_notes,
    "read_note": impl_read_note,
    "update_note": impl_update_note,
    "delete_note": impl_delete_note,
    "send_note": impl_send_note,
    "start_timer": impl_start_timer,
    "list_timers": impl_list_timers,
    "cancel_timer": impl_cancel_timer,
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
