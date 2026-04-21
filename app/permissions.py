from fastapi import HTTPException
from app.models import User

CAPABILITIES = [
    "view_own_tasks",
    "update_own_tasks",
    "comment_on_own_tasks",
    "view_others_tasks",
    "dm_coordinator",
    "start_timer",
    "create_note",
]


def require(user: User, capability: str) -> None:
    """Raise 403 if user lacks capability. Admin always passes."""
    if user.role == "admin":
        return
    if not user.has_capability(capability):
        raise HTTPException(status_code=403, detail=f"Missing permission: {capability}")


def require_admin(user: User) -> None:
    """Raise 403 if user is not admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
