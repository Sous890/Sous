from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Task, User, TASK_STATUSES, TASK_STATUS_COLORS
from app.permissions import require, require_admin

router = APIRouter(prefix="/tasks")
templates = Jinja2Templates(directory="app/templates")


def _get_user_or_redirect(request: Request):
    """Return current_user or raise a redirect to /login."""
    user = request.state.current_user
    if user is None:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


# ---------------------------------------------------------------------------
# GET /tasks  — list view
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def list_tasks(request: Request, db: Session = Depends(get_session)):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if user.role == "admin":
        tasks = (
            db.query(Task)
            .order_by(Task.created_at.desc())
            .all()
        )
    else:
        require(user, "view_own_tasks")
        tasks = (
            db.query(Task)
            .filter(Task.assignee_id == user.id)
            .order_by(Task.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        request, "tasks_list.html",
        {
            "current_user": user,
            "tasks": tasks,
            "status_colors": TASK_STATUS_COLORS,
        },
    )


# ---------------------------------------------------------------------------
# GET /tasks/new  — creation form (admin only)
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
def new_task_form(request: Request, db: Session = Depends(get_session)):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    assignees = db.query(User).filter_by(is_active=True).order_by(User.nickname).all()
    return templates.TemplateResponse(
        request, "task_new.html",
        {
            "current_user": user,
            "assignees": assignees,
            "statuses": TASK_STATUSES,
        },
    )


# ---------------------------------------------------------------------------
# POST /tasks/new  — create task (admin only)
# ---------------------------------------------------------------------------

@router.post("/new")
def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    assignee_id: str = Form(...),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    assignee = db.get(User, assignee_id)
    if not assignee:
        raise HTTPException(status_code=400, detail="Invalid assignee")

    task = Task(
        title=title.strip(),
        description=description.strip() or None,
        assignee_id=assignee_id,
        created_by_id=user.id,
        status="assigned",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return RedirectResponse(url=f"/tasks/{task.id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /tasks/{id}  — detail view
# ---------------------------------------------------------------------------

@router.get("/{task_id}", response_class=HTMLResponse)
def task_detail(
    request: Request,
    task_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Workers can only see their own tasks
    if user.role != "admin" and task.assignee_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    assignees = db.query(User).filter_by(is_active=True).order_by(User.nickname).all() if user.role == "admin" else []

    return templates.TemplateResponse(
        request, "task_detail.html",
        {
            "current_user": user,
            "task": task,
            "statuses": TASK_STATUSES,
            "status_colors": TASK_STATUS_COLORS,
            "assignees": assignees,
        },
    )


# ---------------------------------------------------------------------------
# POST /tasks/{id}/status  — change status
# ---------------------------------------------------------------------------

@router.post("/{task_id}/status")
def update_status(
    request: Request,
    task_id: str,
    status: str = Form(...),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if user.role != "admin":
        # Worker must have permission AND be the assignee
        require(user, "update_own_tasks")
        if task.assignee_id != user.id:
            raise HTTPException(status_code=403, detail="Not your task")

    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    task.status = status
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url="/tasks", status_code=303)


# ---------------------------------------------------------------------------
# POST /tasks/{id}/reassign  — change assignee (admin only)
# ---------------------------------------------------------------------------

@router.post("/{task_id}/reassign")
def reassign_task(
    request: Request,
    task_id: str,
    assignee_id: str = Form(...),
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    assignee = db.get(User, assignee_id)
    if not assignee:
        raise HTTPException(status_code=400, detail="Invalid assignee")

    task.assignee_id = assignee_id
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /tasks/{id}/delete  — hard delete (admin only)
# ---------------------------------------------------------------------------

@router.post("/{task_id}/delete")
def delete_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_session),
):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    require_admin(user)

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()
    return RedirectResponse(url="/tasks", status_code=303)
