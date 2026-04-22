"""
Agent routes: /chat (UI), /ask (API), /reset (clear history).

Session history is stored in memory, keyed by (user_id, session_id).
It is not persisted across server restarts — that's intentional for alpha.
"""
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.agent import loop as agent_loop

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# In-memory history store: (user_id, session_id) -> list of message dicts
_HISTORIES: dict[tuple[str, str], list] = {}


class AskBody(BaseModel):
    session_id: str | None = None
    question: str


class ResetBody(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# GET /chat — chat UI
# ---------------------------------------------------------------------------

@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    user = request.state.current_user
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "chat.html", {"current_user": user})


# ---------------------------------------------------------------------------
# POST /ask
# ---------------------------------------------------------------------------

@router.post("/ask")
def ask(request: Request, body: AskBody, db: Session = Depends(get_session)):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    if not body.question.strip():
        return JSONResponse({"error": "Empty question"}, status_code=400)

    session_id = body.session_id or str(uuid.uuid4())
    key = (user.id, session_id)
    history = _HISTORIES.get(key, [])

    try:
        answer, updated = agent_loop.ask(user, body.question.strip(), history, db)
        _HISTORIES[key] = updated
        return {"session_id": session_id, "answer": answer}
    except Exception as exc:
        # Surface the real error to the client instead of a generic 500
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /reset
# ---------------------------------------------------------------------------

@router.post("/reset")
def reset(request: Request, body: ResetBody):
    user = request.state.current_user
    if user is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    key = (user.id, body.session_id)
    _HISTORIES.pop(key, None)
    return {"ok": True}
