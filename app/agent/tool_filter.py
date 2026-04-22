"""
Per-user tool filtering.

tools_for(user) returns only the tool schemas this user is allowed to invoke.
Admin gets everything. Workers get a filtered subset based on their permissions.

This is the first line of defense. Tool implementations re-check permissions
internally as a second line.
"""
from app.models import User
from app.agent.tools import (
    LIST_MY_TASKS_TOOL,
    LIST_ALL_TASKS_TOOL,
    UPDATE_TASK_STATUS_TOOL,
    ADD_COMMENT_TOOL,
    CREATE_TASK_TOOL,
    ASSIGN_TASK_TOOL,
    SEND_DM_TOOL,
    LIST_USERS_TOOL,
    CREATE_NOTE_TOOL,
    LIST_MY_NOTES_TOOL,
    READ_NOTE_TOOL,
    UPDATE_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    SEND_NOTE_TOOL,
    START_TIMER_TOOL,
    LIST_TIMERS_TOOL,
    CANCEL_TIMER_TOOL,
)


def tools_for(user: User) -> list[dict]:
    """Return the list of tool schemas this user may invoke."""
    if user.role == "admin":
        return [
            LIST_MY_TASKS_TOOL,
            LIST_ALL_TASKS_TOOL,
            UPDATE_TASK_STATUS_TOOL,
            ADD_COMMENT_TOOL,
            CREATE_TASK_TOOL,
            ASSIGN_TASK_TOOL,
            SEND_DM_TOOL,
            LIST_USERS_TOOL,
            CREATE_NOTE_TOOL,
            LIST_MY_NOTES_TOOL,
            READ_NOTE_TOOL,
            UPDATE_NOTE_TOOL,
            DELETE_NOTE_TOOL,
            SEND_NOTE_TOOL,
            START_TIMER_TOOL,
            LIST_TIMERS_TOOL,
            CANCEL_TIMER_TOOL,
        ]

    caps = user.permission_set()
    tools = []

    if "view_own_tasks" in caps:
        tools.append(LIST_MY_TASKS_TOOL)
    if "view_others_tasks" in caps:
        tools.append(LIST_ALL_TASKS_TOOL)
    if "update_own_tasks" in caps:
        tools.append(UPDATE_TASK_STATUS_TOOL)
    if "comment_on_own_tasks" in caps:
        tools.append(ADD_COMMENT_TOOL)
    if "dm_coordinator" in caps:
        tools.append(SEND_DM_TOOL)
    if "create_note" in caps:
        tools.append(CREATE_NOTE_TOOL)
        tools.append(LIST_MY_NOTES_TOOL)
        tools.append(READ_NOTE_TOOL)
        tools.append(UPDATE_NOTE_TOOL)
        tools.append(DELETE_NOTE_TOOL)
    if "create_note" in caps and "dm_coordinator" in caps:
        tools.append(SEND_NOTE_TOOL)
    if "start_timer" in caps:
        tools.append(START_TIMER_TOOL)
        tools.append(LIST_TIMERS_TOOL)
        tools.append(CANCEL_TIMER_TOOL)

    return tools
