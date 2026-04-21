from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app import auth

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    from app.models import User
    user = db.query(User).filter_by(username=username.lower().strip()).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid username or password."},
            status_code=401,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Account is disabled."},
            status_code=403,
        )

    token = auth.create_session(user, db, request)

    # Update last login
    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    response = RedirectResponse(url="/", status_code=303)
    auth.set_session_cookie(response, token)
    return response


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_session)):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.delete_session(token, db)
    response = RedirectResponse(url="/login", status_code=303)
    auth.delete_session_cookie(response)
    return response
