from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import DirectMessage, User
from app.permissions import require

router = APIRouter(prefix="/dm")
templates = Jinja2Templates(directory="app/templates")


def _first_active_admin(db: Session) -> User | None:
    """Return the first active admin by created_at. Used for worker redirect."""
    return (
        db.query(User)
        .filter_by(role="admin", is_active=True)
        .order_by(User.created_at)
        .first()
    )


def _mark_thread_read(current_user: User, other_user_id: str, db: Session) -> None:
    """Mark all messages sent TO current_user FROM other_user as read."""
    now = datetime.now(timezone.utc)
    (
        db.query(DirectMessage)
        .filter(
            DirectMessage.recipient_id == current_user.id,
            DirectMessage.sender_id == other_user_id,
            DirectMessage.read_at == None,  # noqa: E711
        )
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()


# ---------------------------------------------------------------------------
# GET /dm  — thread list (admin) or redirect to admin thread (worker)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def dm_index(request: Request, db: Session = Depends(get_session)):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if user.role != "admin":
        # Workers go straight to the single admin thread
        require(user, "dm_coordinator")
        admin = _first_active_admin(db)
        if admin is None:
            return templates.TemplateResponse(
                request, "dm_list.html",
                {"current_user": user, "error": "No admin available to message."},
            )
        return RedirectResponse(url=f"/dm/{admin.id}", status_code=303)

    # Admin: build thread list grouped by other participant
    # Get all users who have exchanged DMs with admin
    sent = db.query(DirectMessage.recipient_id).filter_by(sender_id=user.id)
    received = db.query(DirectMessage.sender_id).filter_by(recipient_id=user.id)
    other_ids = {r[0] for r in sent.all()} | {r[0] for r in received.all()}

    threads = []
    for other_id in other_ids:
        other_user = db.get(User, other_id)
        if not other_user:
            continue
        # Latest message in thread
        latest = (
            db.query(DirectMessage)
            .filter(
                or_(
                    and_(DirectMessage.sender_id == user.id, DirectMessage.recipient_id == other_id),
                    and_(DirectMessage.sender_id == other_id, DirectMessage.recipient_id == user.id),
                )
            )
            .order_by(DirectMessage.created_at.desc())
            .first()
        )
        # Unread = messages sent TO admin FROM other_user
        unread = (
            db.query(DirectMessage)
            .filter(
                DirectMessage.recipient_id == user.id,
                DirectMessage.sender_id == other_id,
                DirectMessage.read_at == None,  # noqa: E711
            )
            .count()
        )
        threads.append({
            "other_user": other_user,
            "latest": latest,
            "unread": unread,
        })

    # Sort by latest message descending
    threads.sort(key=lambda t: t["latest"].created_at, reverse=True)

    return templates.TemplateResponse(
        request, "dm_list.html",
        {"current_user": user, "threads": threads},
    )


# ---------------------------------------------------------------------------
# GET /dm/{other_user_id}  — conversation view
# ---------------------------------------------------------------------------

@router.get("/{other_user_id}", response_class=HTMLResponse)
def dm_thread(
    request: Request,
    other_user_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    other = db.get(User, other_user_id)
    if other is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Access rule: worker can only view threads with an admin
    if user.role != "admin":
        require(user, "dm_coordinator")
        if other.role != "admin":
            raise HTTPException(status_code=403, detail="Workers can only message the coordinator")

    # Mark incoming messages as read
    _mark_thread_read(user, other_user_id, db)

    # Load thread chronologically
    messages = (
        db.query(DirectMessage)
        .filter(
            or_(
                and_(DirectMessage.sender_id == user.id, DirectMessage.recipient_id == other_user_id),
                and_(DirectMessage.sender_id == other_user_id, DirectMessage.recipient_id == user.id),
            )
        )
        .order_by(DirectMessage.created_at)
        .all()
    )

    # Workers can always reply; admin can always reply; check dm_coordinator for workers
    can_send = user.role == "admin" or user.has_capability("dm_coordinator")

    return templates.TemplateResponse(
        request, "dm_thread.html",
        {
            "current_user": user,
            "other": other,
            "messages": messages,
            "can_send": can_send,
        },
    )


# ---------------------------------------------------------------------------
# POST /dm/{other_user_id}/send  — send a message
# ---------------------------------------------------------------------------

@router.post("/{other_user_id}/send")
def send_dm(
    request: Request,
    other_user_id: str,
    body: str = Form(...),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    other = db.get(User, other_user_id)
    if other is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Permission check for workers
    if user.role != "admin":
        require(user, "dm_coordinator")
        # Enforce 1:1 admin-worker rule — worker cannot DM another worker
        if other.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Workers can only message the coordinator, not other workers",
            )

    # Even admins can't DM other admins in this app (single-admin alpha)
    # But don't block it — it's a natural edge case to leave open for now

    body = body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    msg = DirectMessage(
        sender_id=user.id,
        recipient_id=other_user_id,
        body=body,
    )
    db.add(msg)
    db.commit()
    return RedirectResponse(url=f"/dm/{other_user_id}", status_code=303)
