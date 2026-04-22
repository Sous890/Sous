import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Text, Integer,
    DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    nickname = Column(String(64), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(16), nullable=False)          # 'admin' or 'worker'
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    permissions = relationship(
        "Permission",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Permission.user_id",
    )
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )

    def permission_set(self) -> set[str]:
        return {p.capability for p in self.permissions}

    def has_capability(self, cap: str) -> bool:
        if self.role == "admin":
            return True
        return cap in self.permission_set()


class Permission(Base):
    __tablename__ = "permissions"

    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True, nullable=False
    )
    capability = Column(String(64), primary_key=True, nullable=False)
    granted_at = Column(DateTime(timezone=True), default=_now)
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="permissions", foreign_keys=[user_id])


class UserSession(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=_now)
    user_agent = Column(Text, nullable=True)

    user = relationship("User", back_populates="sessions")


# Valid task statuses and their display labels / pill colors
TASK_STATUSES = ["assigned", "in_progress", "blocked", "done"]
TASK_STATUS_COLORS = {
    "assigned":    "#888",
    "in_progress": "#2980b9",
    "blocked":     "#e67e22",
    "done":        "#27ae60",
}


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    assignee_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_by_id = Column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    status = Column(String(32), nullable=False, default="assigned")
    # reserved for Weekend 3 — no FK constraints until those tables exist
    timer_id = Column(String(36), nullable=True)
    note_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now)

    assignee = relationship(
        "User", foreign_keys=[assignee_id], backref="assigned_tasks"
    )
    creator = relationship(
        "User", foreign_keys=[created_by_id], backref="created_tasks"
    )
    comments = relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at",
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    task = relationship("Task", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])
