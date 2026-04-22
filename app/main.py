from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SESSION_SECRET
from app.db import get_session as _get_db
from app import auth as auth_mod
from app.routes import auth_routes, admin_routes, root_routes, task_routes, dm_routes, agent_routes
from app import notifications as notif_mod

app = FastAPI(title="Team Agent")

# Session middleware (server-side flash storage via signed cookie)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Middleware: attach current_user to every request
@app.middleware("http")
async def attach_user(request: Request, call_next):
    db = next(_get_db())
    try:
        user = auth_mod.get_current_user(request, db)
        request.state.current_user = user
        request.state.db = db
        request.state.unread_count = notif_mod.unread_task_count(user, db)
        request.state.unread_dm_count = notif_mod.unread_dm_count(user, db)
        response = await call_next(request)
        return response
    finally:
        db.close()


# Routers
app.include_router(root_routes.router)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(task_routes.router)
app.include_router(dm_routes.router)
app.include_router(agent_routes.router)
