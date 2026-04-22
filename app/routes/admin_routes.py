import random
import string

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app import auth
from app.models import (
    User, Permission, UserSession,
    Task, TaskComment, TaskView, DirectMessage,
    Note, Timer, CalendarEvent, EventAttendee,
)
from app.permissions import CAPABILITIES, require_admin

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

FLASH_KEY = "_flash_temp_password"


def _gen_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


@router.get("/users", response_class=HTMLResponse)
def list_users(request: Request, db: Session = Depends(get_session)):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    users = db.query(User).order_by(User.created_at).all()
    # Pop the one-time temp password flash
    temp_info = request.session.pop(FLASH_KEY, None)
    flash_success = request.session.pop("_flash_success", None)
    flash_error = request.session.pop("_flash_error", None)

    return templates.TemplateResponse(
        request, "admin_users.html",
        {
            "current_user": user,
            "users": users,
            "capabilities": CAPABILITIES,
            "temp_info": temp_info,
            "flash_success": flash_success,
            "flash_error": flash_error,
        },
    )


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(...),
    nickname: str = Form(...),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    username = username.lower().strip()
    existing = db.query(User).filter_by(username=username).first()
    if existing:
        users = db.query(User).order_by(User.created_at).all()
        return templates.TemplateResponse(
            request, "admin_users.html",
            {
                "current_user": user,
                "users": users,
                "capabilities": CAPABILITIES,
                "temp_info": None,
                "error": f"Username '{username}' already exists.",
            },
            status_code=400,
        )

    temp_password = _gen_password()
    new_user = User(
        username=username,
        nickname=nickname.strip(),
        password_hash=auth.hash_password(temp_password),
        role="worker",
        created_by=user.id,
    )
    db.add(new_user)
    db.commit()

    # Store temp password in session for one-time display
    request.session[FLASH_KEY] = {
        "username": username,
        "nickname": nickname.strip(),
        "password": temp_password,
    }

    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/permissions")
def toggle_permission(
    request: Request,
    user_id: str,
    capability: str = Form(...),
    db: Session = Depends(get_session),
):
    current = request.state.current_user
    if current is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(current)

    if capability not in CAPABILITIES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Unknown capability")

    existing = (
        db.query(Permission)
        .filter_by(user_id=user_id, capability=capability)
        .first()
    )
    if existing:
        db.delete(existing)
    else:
        db.add(Permission(
            user_id=user_id,
            capability=capability,
            granted_by=current.id,
        ))
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


# ---------------------------------------------------------------------------
# Account removal — guarded helpers
# ---------------------------------------------------------------------------

def _count_active_admins(db: Session, exclude_user_id: str | None = None) -> int:
    q = db.query(User).filter(User.role == "admin", User.is_active == True)  # noqa: E712
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    return q.count()


def _load_target_user(db: Session, user_id: str) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


def _guard_self_or_last_admin(current: User, target: User, db: Session) -> str | None:
    """Return an error message, or None if the action is allowed."""
    if target.id == current.id:
        return "You cannot remove your own account."
    if target.role == "admin" and target.is_active:
        # Would this leave zero active admins?
        if _count_active_admins(db, exclude_user_id=target.id) == 0:
            return "Cannot remove the last remaining active admin."
    return None


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_session),
):
    current = request.state.current_user
    if current is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(current)

    target = _load_target_user(db, user_id)
    err = _guard_self_or_last_admin(current, target, db)
    if err:
        request.session["_flash_error"] = err
        return RedirectResponse(url="/admin/users", status_code=303)

    target.is_active = False
    # Invalidate all active sessions for this user so they can't keep browsing.
    db.query(UserSession).filter(UserSession.user_id == target.id).delete()
    db.commit()
    request.session["_flash_success"] = (
        f"Deactivated {target.nickname} ({target.username}). "
        f"Their history is preserved."
    )
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/reactivate")
def reactivate_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_session),
):
    current = request.state.current_user
    if current is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(current)

    target = _load_target_user(db, user_id)
    target.is_active = True
    db.commit()
    request.session["_flash_success"] = f"Reactivated {target.nickname}."
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: str,
    confirm: str = Form(""),
    db: Session = Depends(get_session),
):
    """
    Hard delete. Requires the admin to type the target's username as confirmation.
    Cascades: sessions, permissions, task_views, event_attendees are already CASCADE.
    We explicitly clean up tasks authored-by, comments-by, DMs, notes, timers,
    and calendar events created-by so FK constraints don't block deletion.
    """
    current = request.state.current_user
    if current is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(current)

    target = _load_target_user(db, user_id)
    err = _guard_self_or_last_admin(current, target, db)
    if err:
        request.session["_flash_error"] = err
        return RedirectResponse(url="/admin/users", status_code=303)

    if confirm.strip().lower() != target.username.lower():
        request.session["_flash_error"] = (
            f"Deletion not confirmed — you must type '{target.username}' exactly."
        )
        return RedirectResponse(url="/admin/users", status_code=303)

    uid = target.id
    nickname = target.nickname
    username = target.username

    # Tasks assigned TO this user are deleted (cascades comments, views).
    assigned_tasks = db.query(Task).filter(Task.assignee_id == uid).all()
    for t in assigned_tasks:
        db.delete(t)

    # Tasks created BY this user — reassign creator to the current admin so we
    # don't lose the task history for other users.
    db.query(Task).filter(Task.created_by_id == uid).update(
        {Task.created_by_id: current.id}, synchronize_session=False
    )

    # Comments authored by this user on OTHER people's tasks — delete them.
    db.query(TaskComment).filter(TaskComment.author_id == uid).delete(
        synchronize_session=False
    )

    # DMs sent or received — delete.
    db.query(DirectMessage).filter(
        (DirectMessage.sender_id == uid) | (DirectMessage.recipient_id == uid)
    ).delete(synchronize_session=False)

    # Notes & timers owned by this user (already CASCADE, but be explicit).
    db.query(Note).filter(Note.owner_id == uid).delete(synchronize_session=False)
    db.query(Timer).filter(Timer.owner_id == uid).delete(synchronize_session=False)

    # Calendar events created by this user — delete (cascades attendees/tasks).
    events = db.query(CalendarEvent).filter(CalendarEvent.created_by_id == uid).all()
    for e in events:
        db.delete(e)

    # EventAttendee rows for this user are cleaned by user CASCADE, but flush them
    # explicitly for safety.
    db.query(EventAttendee).filter(EventAttendee.user_id == uid).delete(
        synchronize_session=False
    )

    # Finally delete the user. Permissions and sessions cascade automatically.
    db.delete(target)
    db.commit()

    request.session["_flash_success"] = (
        f"Permanently deleted {nickname} ({username})."
    )
    return RedirectResponse(url="/admin/users", status_code=303)
