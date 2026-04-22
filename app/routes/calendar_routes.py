"""
Calendar routes.

Admin-only:
  GET  /admin/calendar                       — month view (with optional ?month=YYYY-MM)
  GET  /admin/calendar/new                   — event creation form
  POST /admin/calendar/new                   — create event
  GET  /admin/calendar/{event_id}            — event detail (edit)
  POST /admin/calendar/{event_id}            — update event
  POST /admin/calendar/{event_id}/delete     — delete event
  POST /admin/calendar/{event_id}/attendees  — add attendee
  POST /admin/calendar/{event_id}/attendees/{user_id}/remove  — remove attendee
  POST /admin/calendar/{event_id}/tasks      — tag a task to event
  POST /admin/calendar/{event_id}/tasks/{task_id}/remove      — untag task

Worker-visible:
  GET  /calendar                             — month view of events the user is invited to
  GET  /calendar/{event_id}                  — event detail (read-only)
"""
from calendar import Calendar as _PyCal
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    User, Task, CalendarEvent, EventAttendee, EventTask,
    TASK_STATUS_COLORS,
)
from app.permissions import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_month(month_str: str | None) -> date:
    """Parse ?month=YYYY-MM → first-of-month date. Default to today's month."""
    if month_str:
        try:
            y, m = month_str.split("-")
            return date(int(y), int(m), 1)
        except (ValueError, TypeError):
            pass
    today = date.today()
    return date(today.year, today.month, 1)


def _month_bounds(anchor: date):
    """Return (start_of_first_visible_day, start_of_day_after_last_visible, weeks_grid).
    We display a 6-week grid starting on Sunday, so we pad outside the month."""
    cal = _PyCal(firstweekday=6)  # Sunday
    weeks = cal.monthdatescalendar(anchor.year, anchor.month)
    first_day = weeks[0][0]
    last_day = weeks[-1][-1]
    start = datetime.combine(first_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end, weeks


def _shift_month(anchor: date, delta: int) -> date:
    y, m = anchor.year, anchor.month + delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


def _parse_dt_local(s: str) -> datetime:
    """Parse 'YYYY-MM-DDTHH:MM' from a datetime-local input.
    Stored as UTC (we treat the user's input as UTC for simplicity in this build)."""
    if not s:
        raise HTTPException(status_code=400, detail="Datetime is required")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Bad datetime: {s}")


def _fmt_dt_local(dt: datetime) -> str:
    """Format a datetime for <input type=datetime-local>."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


def _visible_events_for(user: User, db: Session, start: datetime, end: datetime):
    """Events the user can see in the [start, end) window."""
    if user.role == "admin":
        q = db.query(CalendarEvent).filter(
            CalendarEvent.starts_at < end,
            CalendarEvent.ends_at >= start,
        )
    else:
        q = (
            db.query(CalendarEvent)
            .join(EventAttendee, EventAttendee.event_id == CalendarEvent.id)
            .filter(
                EventAttendee.user_id == user.id,
                CalendarEvent.starts_at < end,
                CalendarEvent.ends_at >= start,
            )
        )
    return q.order_by(CalendarEvent.starts_at).all()


def _user_can_view_event(user: User, event: CalendarEvent) -> bool:
    if user.role == "admin":
        return True
    return any(a.user_id == user.id for a in event.attendees)


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------

@router.get("/admin/calendar", response_class=HTMLResponse)
def admin_calendar(
    request: Request,
    month: str | None = None,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    anchor = _parse_month(month)
    start, end, weeks = _month_bounds(anchor)
    events = _visible_events_for(user, db, start, end)

    # Bucket events by date (uses UTC date of starts_at)
    events_by_day: dict[date, list] = defaultdict(list)
    for ev in events:
        events_by_day[ev.starts_at.date()].append(ev)

    flash_success = request.session.pop("_flash_cal_success", None)
    flash_error = request.session.pop("_flash_cal_error", None)

    return templates.TemplateResponse(
        request, "calendar_month.html",
        {
            "current_user": user,
            "anchor": anchor,
            "weeks": weeks,
            "events_by_day": events_by_day,
            "prev_month": _shift_month(anchor, -1).strftime("%Y-%m"),
            "next_month": _shift_month(anchor, +1).strftime("%Y-%m"),
            "today": date.today(),
            "is_admin_view": True,
            "flash_success": flash_success,
            "flash_error": flash_error,
        },
    )


@router.get("/admin/calendar/new", response_class=HTMLResponse)
def admin_event_new_form(
    request: Request,
    date_str: str | None = None,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    # Default the form to 9:00am on the given date, or today at next hour.
    if date_str:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            d = date.today()
    else:
        d = date.today()
    default_start = datetime.combine(d, time(9, 0), tzinfo=timezone.utc)
    default_end = default_start + timedelta(hours=1)

    users = db.query(User).filter_by(is_active=True).order_by(User.nickname).all()
    tasks = db.query(Task).order_by(Task.created_at.desc()).limit(200).all()

    return templates.TemplateResponse(
        request, "calendar_event_form.html",
        {
            "current_user": user,
            "event": None,
            "users": users,
            "tasks": tasks,
            "default_start": _fmt_dt_local(default_start),
            "default_end": _fmt_dt_local(default_end),
            "selected_user_ids": set(),
            "selected_task_ids": set(),
            "status_colors": TASK_STATUS_COLORS,
        },
    )


@router.post("/admin/calendar/new")
def admin_event_create(
    request: Request,
    title: str = Form(...),
    starts_at: str = Form(...),
    ends_at: str = Form(...),
    description: str = Form(""),
    location: str = Form(""),
    all_day: str = Form(""),
    attendee_ids: list[str] = Form(default=[]),
    task_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    starts = _parse_dt_local(starts_at)
    ends = _parse_dt_local(ends_at)
    if ends < starts:
        raise HTTPException(status_code=400, detail="End time must be after start")

    event = CalendarEvent(
        title=title.strip(),
        description=(description.strip() or None),
        location=(location.strip() or None),
        starts_at=starts,
        ends_at=ends,
        all_day=bool(all_day),
        created_by_id=user.id,
    )
    db.add(event)
    db.flush()  # get event.id

    # Attach attendees
    for uid in attendee_ids:
        if uid and db.get(User, uid):
            db.add(EventAttendee(event_id=event.id, user_id=uid))

    # Attach tasks
    for tid in task_ids:
        if tid and db.get(Task, tid):
            db.add(EventTask(event_id=event.id, task_id=tid))

    db.commit()
    db.refresh(event)
    request.session["_flash_cal_success"] = f"Created event '{event.title}'."
    return RedirectResponse(
        url=f"/admin/calendar/{event.id}", status_code=303
    )


@router.get("/admin/calendar/{event_id}", response_class=HTMLResponse)
def admin_event_detail(
    request: Request,
    event_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    users = db.query(User).filter_by(is_active=True).order_by(User.nickname).all()
    tasks = db.query(Task).order_by(Task.created_at.desc()).limit(200).all()

    selected_user_ids = {a.user_id for a in event.attendees}
    selected_task_ids = {et.task_id for et in event.tagged_tasks}

    flash_success = request.session.pop("_flash_event_success", None)
    flash_error = request.session.pop("_flash_event_error", None)

    return templates.TemplateResponse(
        request, "calendar_event_form.html",
        {
            "current_user": user,
            "event": event,
            "users": users,
            "tasks": tasks,
            "default_start": _fmt_dt_local(event.starts_at),
            "default_end": _fmt_dt_local(event.ends_at),
            "selected_user_ids": selected_user_ids,
            "selected_task_ids": selected_task_ids,
            "status_colors": TASK_STATUS_COLORS,
            "flash_success": flash_success,
            "flash_error": flash_error,
        },
    )


@router.post("/admin/calendar/{event_id}")
def admin_event_update(
    request: Request,
    event_id: str,
    title: str = Form(...),
    starts_at: str = Form(...),
    ends_at: str = Form(...),
    description: str = Form(""),
    location: str = Form(""),
    all_day: str = Form(""),
    attendee_ids: list[str] = Form(default=[]),
    task_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    starts = _parse_dt_local(starts_at)
    ends = _parse_dt_local(ends_at)
    if ends < starts:
        raise HTTPException(status_code=400, detail="End time must be after start")

    event.title = title.strip()
    event.description = description.strip() or None
    event.location = location.strip() or None
    event.starts_at = starts
    event.ends_at = ends
    event.all_day = bool(all_day)
    event.updated_at = datetime.now(timezone.utc)

    # Replace attendees set
    desired_users = {uid for uid in attendee_ids if uid}
    current_users = {a.user_id for a in event.attendees}
    for uid in current_users - desired_users:
        db.query(EventAttendee).filter_by(event_id=event.id, user_id=uid).delete()
    for uid in desired_users - current_users:
        if db.get(User, uid):
            db.add(EventAttendee(event_id=event.id, user_id=uid))

    # Replace tagged tasks set
    desired_tasks = {tid for tid in task_ids if tid}
    current_tasks = {et.task_id for et in event.tagged_tasks}
    for tid in current_tasks - desired_tasks:
        db.query(EventTask).filter_by(event_id=event.id, task_id=tid).delete()
    for tid in desired_tasks - current_tasks:
        if db.get(Task, tid):
            db.add(EventTask(event_id=event.id, task_id=tid))

    db.commit()
    request.session["_flash_event_success"] = "Event updated."
    return RedirectResponse(url=f"/admin/calendar/{event.id}", status_code=303)


@router.post("/admin/calendar/{event_id}/delete")
def admin_event_delete(
    request: Request,
    event_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    month_str = event.starts_at.strftime("%Y-%m")
    db.delete(event)
    db.commit()
    request.session["_flash_cal_success"] = "Event deleted."
    return RedirectResponse(url=f"/admin/calendar?month={month_str}", status_code=303)


# ---------------------------------------------------------------------------
# Worker views
# ---------------------------------------------------------------------------

@router.get("/calendar", response_class=HTMLResponse)
def worker_calendar(
    request: Request,
    month: str | None = None,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    # Admins get redirected to the admin view
    if user.role == "admin":
        suffix = f"?month={month}" if month else ""
        return RedirectResponse(url=f"/admin/calendar{suffix}", status_code=303)

    anchor = _parse_month(month)
    start, end, weeks = _month_bounds(anchor)
    events = _visible_events_for(user, db, start, end)

    events_by_day: dict[date, list] = defaultdict(list)
    for ev in events:
        events_by_day[ev.starts_at.date()].append(ev)

    return templates.TemplateResponse(
        request, "calendar_month.html",
        {
            "current_user": user,
            "anchor": anchor,
            "weeks": weeks,
            "events_by_day": events_by_day,
            "prev_month": _shift_month(anchor, -1).strftime("%Y-%m"),
            "next_month": _shift_month(anchor, +1).strftime("%Y-%m"),
            "today": date.today(),
            "is_admin_view": False,
        },
    )


@router.get("/calendar/{event_id}", response_class=HTMLResponse)
def worker_event_detail(
    request: Request,
    event_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _user_can_view_event(user, event):
        raise HTTPException(status_code=404, detail="Event not found")

    return templates.TemplateResponse(
        request, "calendar_event_view.html",
        {
            "current_user": user,
            "event": event,
            "status_colors": TASK_STATUS_COLORS,
        },
    )
