# Weekend 2 — Tasks

**Companion to PRD.md and ARCHITECTURE.md. Read both before starting.**

---

## Goal

Ship a working task system: coordinator creates tasks and assigns them to workers; workers see their own tasks and update status. **No agent yet.** Task comments and DMs come in Weekend 3.

This is pure CRUD + UI. If it takes more than one focused session, something's wrong with the approach.

---

## Before you code: branch off

```bash
cd team-agent
git checkout main
git pull                      # in case you pushed from elsewhere
git push --tags               # back up v0.1-auth to GitHub
git checkout -b weekend-2
```

Now every Weekend 2 commit lands on the `weekend-2` branch. Your `main` branch stays pinned to working Weekend 1 code. If this weekend goes sideways, `git checkout main` puts you back to the working state in one command.

When everything works end-to-end and acceptance tests pass:

```bash
git checkout main
git merge weekend-2
git tag v0.2-tasks
git push --tags
```

---

## Scope: what's IN

**New data:** the `tasks` table from ARCHITECTURE.md. That's it. No comments, no timer/note links yet — they're just columns reserved for Weekend 3.

**New pages:**
- `/tasks` — role-aware. Admin sees all tasks across all users. Worker sees only their own.
- `/tasks/new` — admin-only. Create a task with title, description, assignee dropdown.
- `/tasks/{id}` — detail page. Shows the task. Assignee can change status. Admin can edit everything.

**New permissions wiring:**
- `view_own_tasks` → gates the worker view of `/tasks`
- `update_own_tasks` → gates the status-change form on `/tasks/{id}` for workers
- `view_others_tasks` → gates the expanded worker view (see other workers' tasks read-only). Not critical for Weekend 2 — implement if time, defer if not.

**New admin UI bits:**
- Admin dashboard (`/admin/users`) gets a link to `/tasks`
- Each task detail page has a delete button for admin
- Admin can reassign a task

---

## Scope: what's OUT

- **No agent.** No `/ask` endpoint changes, no new tools. Agent integration is Weekend 3.
- **No comments.** Reserved column exists, feature doesn't.
- **No timer/note attachment.** Reserved columns exist, feature doesn't.
- **No notifications.** Workers discover their new tasks by visiting `/tasks`. A badge counter is Weekend 3 polish.
- **No task editing by workers.** Workers can only change status. Admin owns the data.
- **No task history / audit log.**
- **No search, filter, or sort.** Tasks render in created-at descending order. That's it.
- **No pagination.** Alpha has ~30 tasks max. If someone hits 100 tasks, we'll paginate in Weekend 3.

---

## The status state machine

Four statuses, simple transitions:

```
assigned ──→ in_progress ──→ done
     ↓            ↓            ↑
     └──── blocked ────────────┘
```

- **assigned** — initial state, waiting to be picked up
- **in_progress** — worker has started
- **blocked** — worker can't proceed, needs admin attention
- **done** — worker marks complete

Rules:
- Any status can transition to any other (no enforcement in Weekend 2 — keep it simple)
- Status shows as a colored pill on task cards
- Admin can set any status; worker can set any status on their own tasks

We may tighten this in Weekend 3 based on real usage. Don't overbuild now.

---

## Acceptance test — 12 steps

Running locally, fresh DB (you can wipe with `alembic downgrade base && alembic upgrade head && python seed_admin.py`):

1. Start server, log in as admin
2. Go to `/admin/users`, create a worker named "otter" (or whatever nickname)
3. Grant otter `view_own_tasks` and `update_own_tasks` permissions
4. Click link to `/tasks` from admin dashboard — sees empty state "No tasks yet"
5. Click "New task" — form appears with title, description, assignee dropdown (admin + otter)
6. Create a task: title "Write Q3 report", assign to otter, status defaults to "assigned"
7. Tasks list now shows the task with otter's nickname and the status pill
8. Log out, log in as otter
9. Visit `/tasks` — sees the one task assigned to them
10. Click into it, change status to "in_progress", redirects back to `/tasks` showing new status
11. Log back in as admin, visit `/tasks` — sees otter's task now in "in_progress"
12. Admin reassigns the task to themselves, deletes it, confirms empty state returns

If all 12 pass, Weekend 2 is done.

---

## Claude Code prompt for Weekend 2

Paste this verbatim into Claude Code inside your `team-agent` repo (on the `weekend-2` branch):

---

> Read PRD.md, ARCHITECTURE.md, and WEEKEND_2.md before writing any code. We are building Weekend 2: tasks.
>
> **Scope (do not exceed):**
> - `tasks` table exactly as specified in ARCHITECTURE.md (include the `timer_id` and `note_id` nullable columns even though we don't use them yet — reserved for Weekend 3)
> - Three pages: `/tasks` (list), `/tasks/new` (admin-only creation), `/tasks/{id}` (detail + status change)
> - Permission-gated: workers need `view_own_tasks` to see `/tasks`, `update_own_tasks` to change status
> - Admin can do everything: create, reassign, delete, change status, see all tasks
> - Simple server-rendered Jinja templates. Form posts only. No JavaScript.
>
> **Build these files in order:**
>
> 1. Alembic migration creating the `tasks` table with all columns from ARCHITECTURE.md
>
> 2. Add `Task` SQLAlchemy model to `app/models.py`. Include relationships to `User` for `assignee` and `created_by`. Use `foreign_keys=` explicitly since there are two FKs to users.
>
> 3. `app/routes/task_routes.py` with:
>    - `GET /tasks` — if admin, show all tasks; if worker, show only `assignee_id == current_user.id`. Require `view_own_tasks` for workers.
>    - `GET /tasks/new` — admin only, render form with assignee dropdown populated from all active users
>    - `POST /tasks/new` — admin only, create task, redirect to `/tasks/{id}`
>    - `GET /tasks/{id}` — admin sees always; worker sees only if they're the assignee. 404 otherwise.
>    - `POST /tasks/{id}/status` — change status. Worker needs `update_own_tasks` AND must be the assignee. Admin always allowed.
>    - `POST /tasks/{id}/reassign` — admin only, change assignee_id
>    - `POST /tasks/{id}/delete` — admin only, delete task
>
> 4. Templates in `app/templates/`:
>    - `tasks_list.html` — extends base.html; table or card layout showing title, assignee nickname, status pill, created_at. Admin sees a "New task" button.
>    - `task_new.html` — form: title (text), description (textarea), assignee (select dropdown of active users)
>    - `task_detail.html` — shows title, description, assignee, creator, created_at. Status change form (radio or select + submit). Admin-only reassign dropdown and delete button.
>
> 5. Update `app/templates/base.html` nav to include a "Tasks" link for any logged-in user.
>
> 6. Update `app/templates/admin_users.html` to include a "Tasks" link somewhere.
>
> 7. Update `app/templates/worker_home.html` so the "Hi, {nickname}" page has a "View my tasks" link if they have `view_own_tasks` permission.
>
> 8. Wire the new routes into `app/main.py`.
>
> **Status pill styling:**
> Use these colors in the Jinja template or inline CSS:
> - `assigned` — gray
> - `in_progress` — blue
> - `blocked` — orange
> - `done` — green
>
> Inline CSS is fine. Keep it minimal.
>
> **Critical details:**
> - Every task query for a worker MUST filter by `assignee_id == current_user.id`. Never assume; always filter. This is the core permission boundary.
> - The `/tasks/{id}/status` endpoint must verify BOTH that the user has the permission AND that they're the assignee (or admin). Permission alone isn't enough — a worker with `update_own_tasks` shouldn't be able to change someone else's task.
> - Delete is hard-delete for alpha. No soft delete, no confirmation modal — just a POST button.
> - When admin creates a task, `created_by_id` is the admin's id. When worker changes status, updated_at is bumped.
>
> **Do NOT build:**
> - Comments (Weekend 3)
> - Timer/note attachment (Weekend 3)
> - Agent tools for tasks (Weekend 3)
> - Any JavaScript
> - Pagination, search, filters, sort
> - Notifications
> - Task editing by workers beyond status
>
> When done, run the 12-step acceptance test from WEEKEND_2.md. Report which steps pass and which fail.

---

## What to report back after Claude Code finishes

Same format as Weekend 1 — specific, not vague:

- "All 12 steps pass" or
- "Steps 1-N pass, step N+1 fails with [exact error]"

If any step fails, don't try to fix it mid-weekend. Paste the error here, we diagnose together, then fix in one round rather than three.

---

## If time permits (stretch goals — only if everything above is done and working)

1. Implement `view_others_tasks` — workers with that permission see a read-only "all team tasks" view
2. Add `updated_at` display in human-readable relative form ("2 hours ago") using a simple Jinja filter
3. Basic status filter on the list page (admin view) via query param: `/tasks?status=in_progress`

Do NOT touch these until the 12-step test fully passes.

---

## Red flags — stop and ping PM

- Claude Code starts writing React or adding JavaScript for the task UI. That's scope creep. Halt.
- Claude Code proposes adding comments to the task model "since we're there anyway." No. Weekend 3.
- You find yourself writing more than 500 lines of new code total. Weekend 2 should be smaller than Weekend 1 by volume. If it's not, something's over-engineered.
- You spend more than 30 minutes on any single bug. Something's architecturally off. Pause, paste error here.

---

## Sign-off

- [x] PM (Claude): approved
- [ ] Coordinator: to be signed off after 12-step test passes
