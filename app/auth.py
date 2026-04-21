from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, Response
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import User, UserSession
from app import config

_crypt = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "ta_auth"
SESSION_DAYS = 30


def hash_password(plain: str) -> str:
    return _crypt.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _crypt.verify(plain, hashed)


def create_session(user: User, db: Session, request: Request) -> str:
    """Create a DB session row and return the session token (UUID)."""
    now = datetime.now(timezone.utc)
    sess = UserSession(
        user_id=user.id,
        expires_at=now + timedelta(days=SESSION_DAYS),
        last_seen_at=now,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess.id


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=config.SECURE_COOKIES,
        samesite="lax",
        max_age=SESSION_DAYS * 86400,
    )


def delete_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, httponly=True, samesite="lax")


def get_current_user(request: Request, db: Session) -> Optional[User]:
    """Read the session cookie, validate, return User or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    now = datetime.now(timezone.utc)
    sess = db.get(UserSession, token)
    if sess is None:
        return None
    if sess.expires_at.replace(tzinfo=timezone.utc) < now:
        db.delete(sess)
        db.commit()
        return None

    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None

    # Touch last_seen
    sess.last_seen_at = now
    db.commit()
    return user


def delete_session(token: str, db: Session) -> None:
    sess = db.get(UserSession, token)
    if sess:
        db.delete(sess)
        db.commit()
