"""
Widget endpoints — polled and mutated by the sidebar / floating cards.

GET  /widgets/data                  — poll (timers, notes, tasks, DM count)
POST /widgets/notes/{id}            — save note (name + body)
POST /widgets/notes/{id}/delete     — delete note
POST /widgets/timers/{id}/adjust    — extend or shrink a timer by delta_seconds

All write endpoints scope to the authenticated user's own objects only.
Uses request.state.db so we share the middleware-opened DB session.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models import Note, Task, Timer

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /widgets/data
# ---------------------------------------------------------------------------

@router.get("/widgets/data")
def widgets_data(request: Request):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db  = request.state.db
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    # ---- timers -----------------------------------------------------------
    timers_q = (
        db.query(Timer)
        .filter(Timer.owner_id == user.id, Timer.cancelled == False)
        .order_by(Timer.fires_at)
        .all()
    )

    # Lazy-complete timers whose fires_at has passed
    timers_just_completed = []
    for t in timers_q:
        fires_at = t.fires_at
        if fires_at.tzinfo is None:
            fires_at = fires_at.replace(tzinfo=timezone.utc)
        if not t.fired and fires_at <= now:
            t.fired = True
            timers_just_completed.append(t.id)
    if timers_just_completed:
        db.commit()

    timers_out = []
    for t in timers_q:
        fires_at = t.fires_at
        if fires_at.tzinfo is None:
            fires_at = fires_at.replace(tzinfo=timezone.utc)
        timers_out.append({
            "id": t.id,
            "label": t.label or "Timer",
            "fires_at_ms": int(fires_at.timestamp() * 1000),
            "remaining_seconds": max(0.0, (fires_at - now).total_seconds()),
            "fired": t.fired,
            "cancelled": t.cancelled,
            "duration_seconds": t.duration_seconds,
        })

    # ---- notes ------------------------------------------------------------
    notes_q = (
        db.query(Note)
        .filter(Note.owner_id == user.id)
        .order_by(Note.updated_at.desc())
        .limit(5)
        .all()
    )
    notes_out = [
        {"id": n.id, "name": n.name, "body": n.body, "updated_at": str(n.updated_at)}
        for n in notes_q
    ]

    # ---- tasks ------------------------------------------------------------
    task_filter = [Task.status != "done"]
    if user.role != "admin":
        task_filter.append(Task.assignee_id == user.id)
    tasks_q = (
        db.query(Task)
        .filter(*task_filter)
        .order_by(Task.updated_at.desc())
        .limit(10)
        .all()
    )
    tasks_out = [
        {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "assignee": t.assignee.nickname if t.assignee else "?",
        }
        for t in tasks_q
    ]

    return {
        "server_time_ms": now_ms,
        "timers": timers_out,
        "timers_just_completed": timers_just_completed,
        "notes": notes_out,
        "tasks": tasks_out,
        "unread_dm_count": request.state.unread_dm_count,
    }


# ---------------------------------------------------------------------------
# POST /widgets/notes/{note_id}  — save (name + body)
# ---------------------------------------------------------------------------

class NoteUpdate(BaseModel):
    name: str = ""
    body: str = ""


@router.post("/widgets/notes/{note_id}")
def save_note(note_id: str, payload: NoteUpdate, request: Request):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db = request.state.db
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        return JSONResponse({"error": "Note not found"}, status_code=404)

    name = payload.name.strip()
    if name:
        # Guard against duplicate name (another note already has this name)
        clash = (
            db.query(Note)
            .filter(Note.owner_id == user.id, Note.name == name, Note.id != note_id)
            .first()
        )
        if clash:
            return JSONResponse({"error": f"You already have a note named '{name}'"}, status_code=409)
        note.name = name

    note.body = payload.body
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "id": note_id, "name": note.name}


# ---------------------------------------------------------------------------
# POST /widgets/notes/{note_id}/delete
# ---------------------------------------------------------------------------

@router.post("/widgets/notes/{note_id}/delete")
def delete_note(note_id: str, request: Request):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db = request.state.db
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        return JSONResponse({"error": "Note not found"}, status_code=404)

    db.delete(note)
    db.commit()
    return {"ok": True, "deleted": note_id}


# ---------------------------------------------------------------------------
# POST /widgets/timers/{timer_id}/adjust
# ---------------------------------------------------------------------------

class TimerAdjust(BaseModel):
    delta_seconds: int   # positive = extend, negative = shrink


@router.post("/widgets/timers/{timer_id}/adjust")
def adjust_timer(timer_id: str, payload: TimerAdjust, request: Request):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # Clamp per-request delta to ±1 hour to prevent abuse
    delta = max(-3600, min(3600, payload.delta_seconds))

    db = request.state.db
    timer = db.query(Timer).filter(Timer.id == timer_id, Timer.owner_id == user.id).first()
    if not timer:
        return JSONResponse({"error": "Timer not found"}, status_code=404)
    if timer.cancelled:
        return JSONResponse({"error": "Timer is cancelled"}, status_code=400)

    now = datetime.now(timezone.utc)

    fires_at = timer.fires_at
    if fires_at.tzinfo is None:
        fires_at = fires_at.replace(tzinfo=timezone.utc)

    started_at = timer.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    new_fires_at = fires_at + timedelta(seconds=delta)

    # Cap at 24 hours from original start
    max_fires_at = started_at + timedelta(hours=24)
    if new_fires_at > max_fires_at:
        return JSONResponse({"error": "Cannot extend beyond 24 hours from start"}, status_code=400)

    # If shrinking below now, mark as done immediately
    if new_fires_at <= now:
        timer.fired = True
        timer.fires_at = now
        db.commit()
        return {"ok": True, "fires_at_ms": int(now.timestamp() * 1000), "fired": True}

    timer.fires_at = new_fires_at
    timer.duration_seconds = max(0, int((new_fires_at - started_at).total_seconds()))
    db.commit()
    return {"ok": True, "fires_at_ms": int(new_fires_at.timestamp() * 1000), "fired": False}


# ---------------------------------------------------------------------------
# POST /widgets/timers/{timer_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/widgets/timers/{timer_id}/cancel")
def cancel_timer_widget(timer_id: str, request: Request):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db = request.state.db
    timer = db.query(Timer).filter(Timer.id == timer_id, Timer.owner_id == user.id).first()
    if not timer:
        return JSONResponse({"error": "Timer not found"}, status_code=404)
    if timer.cancelled:
        return JSONResponse({"error": "Already cancelled"}, status_code=400)

    timer.cancelled = True
    db.commit()
    return {"ok": True, "cancelled": timer_id}
