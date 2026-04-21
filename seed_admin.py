"""
Idempotent script to create the admin user from env vars.
Run after `alembic upgrade head`.
"""
import sys
from app.config import ADMIN_USERNAME, ADMIN_NICKNAME, ADMIN_PASSWORD
from app.db import SessionLocal
from app.models import User
from app.auth import hash_password


def main():
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(username=ADMIN_USERNAME).first()
        if existing:
            print(f"Admin already exists: {ADMIN_USERNAME}")
            sys.exit(0)

        admin = User(
            username=ADMIN_USERNAME,
            nickname=ADMIN_NICKNAME,
            password_hash=hash_password(ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: {ADMIN_USERNAME} / {ADMIN_NICKNAME}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
