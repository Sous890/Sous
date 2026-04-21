import random
import string

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app import auth
from app.models import User, Permission
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

    return templates.TemplateResponse(
        request, "admin_users.html",
        {
            "current_user": user,
            "users": users,
            "capabilities": CAPABILITIES,
            "temp_info": temp_info,
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
