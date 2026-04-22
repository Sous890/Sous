"""
Tool-use loop for the team agent.

Pattern mirrors the personal agent: append user turn, call API, if tool_use
execute and append tool_result, repeat until end_turn.
"""
import os
import json

from anthropic import Anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.models import User
from app.agent.tool_filter import tools_for
from app.agent.tools import dispatch

load_dotenv(override=True)

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4096

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


def _system_prompt(user: User, has_tools: bool = True) -> str:
    base = (
        f"You are the team coordinator assistant for {user.nickname}. "
        f"Their role is {user.role}.\n"
        "You can help them with tasks, comments, and direct messages based on their permissions.\n"
        "Be concise. Confirm before destructive actions (task deletion, mass status changes, reassignment).\n"
        "If a tool returns an error, explain the reason to the user in plain language — don't retry the same call.\n"
        "If asked to do something you don't have a tool for, say so plainly."
    )
    if not has_tools:
        base += (
            "\n\nIMPORTANT: You have NO tools available for this user. "
            "They have not been granted any capabilities yet. "
            "Do not attempt to call any functions or tools. "
            "Tell them plainly that they have no capabilities granted and should ask the coordinator."
        )
    return base


def ask(user: User, question: str, history: list, db: Session) -> tuple[str, list]:
    """
    Run one user turn through the tool-use loop.

    Returns (final_text, updated_history).
    history is a list of Anthropic-format message dicts.
    """
    client = _get_client()
    tool_list = tools_for(user)

    history = list(history)
    history.append({"role": "user", "content": question})

    while True:
        kwargs = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": _system_prompt(user, has_tools=bool(tool_list)),
            "messages": history,
        }
        if tool_list:
            kwargs["tools"] = tool_list

        response = client.messages.create(**kwargs)

        # Append assistant turn as-is
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            return ("\n".join(text_parts).strip(), history)

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = dispatch(block.name, block.input, user, db)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            history.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — return whatever text we have
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        return (
            "\n".join(text_parts).strip() or f"(stopped: {response.stop_reason})",
            history,
        )
