# v0.8 — Account removal + Admin calendar

## 1. Account removal

Admins can now remove users from **`/admin/users`**. Two-tier approach:

- **Deactivate** (soft remove — default choice)
  - Sets `is_active = False`. User can't log in (existing auth already blocks inactive users).
  - All active sessions for that user are deleted — they're kicked out immediately on their next request.
  - Tasks, comments, DMs, calendar invites are preserved for history.
  - Reversible: a **Reactivate** button appears on the same row.
- **Delete…** (hard remove — requires typed username confirmation)
  - Permanently deletes the user.
  - Also deletes: tasks assigned *to* them, their DMs, notes, timers, calendar events they created, and any task comments they authored.
  - Tasks *created by* them (but assigned to someone else) are re-homed to the admin doing the deletion, so the assignee doesn't lose their work.
  - Shows an inline red confirmation panel — admin must type the username exactly.

Guardrails:
- An admin cannot remove themselves.
- The last active admin cannot be deactivated or deleted.
- Deactivated accounts still show in the user list (row is greyed out) so they can be reactivated.

## 2. Admin calendar

New pages, admin-only to edit:

| Route                                | Who        | What                                  |
|--------------------------------------|------------|---------------------------------------|
| `GET /admin/calendar`                | Admin only | Month view of all events              |
| `GET/POST /admin/calendar/new`       | Admin only | Create event                          |
| `GET/POST /admin/calendar/{id}`      | Admin only | View / edit event                     |
| `POST /admin/calendar/{id}/delete`   | Admin only | Delete event                          |
| `GET /calendar`                      | Workers    | Month view of events they're invited to |
| `GET /calendar/{id}`                 | Workers    | Read-only event detail (invitees only) |

Month view:
- Sunday-first 6-week grid. Today highlighted. Click any day to view details; admins get a `+` button on hover to quickly create an event on that date.
- Up to 3 events shown per day cell, with `+N more` overflow.
- Events with tagged tasks are colored purple; regular events are blue.
- Prev / Today / Next navigation. `?month=YYYY-MM` in the URL.

## 3. Scheduler (invite users to events)

On the event form, admins tick checkboxes to invite any active users. Invited users:
- See the event on **their** `/calendar` month view.
- Can open it at `/calendar/{id}` and see: time, location, description, the admin who scheduled it, the full attendee list, and any tagged tasks.
- Non-attendee workers get 404 if they try to fetch the event directly.

## 4. Tag tasks to events

On the event form, admins also pick tasks from a checkbox list (most recent 200 shown). Tagged tasks:
- Show on the event detail page with their current status pill and a link to open the task (for admins or the task's assignee).
- Make the event cell in the month grid render purple as a visual cue.
- Are a many-to-many via the new `event_tasks` join table — a task can be tagged to multiple events and vice versa.

## Data model changes

Three new tables (Alembic migration `0007_calendar.py`):

- **`calendar_events`** — id, title, description, location, starts_at, ends_at, all_day, created_by_id, timestamps
- **`event_attendees`** — (event_id, user_id) composite PK, added_at. Cascades on both FKs.
- **`event_tasks`** — (event_id, task_id) composite PK, added_at. Cascades on both FKs.

## Nav

Admins now see a **Calendar** link in the top nav going to `/admin/calendar`. Workers see **Calendar** going to `/calendar`.

## Migrating an existing deploy

```bash
alembic upgrade head   # applies 0007_calendar
# Restart the app. No seed step needed — new tables start empty.
```

## Things intentionally kept simple (worth revisiting later)

- **Time zones.** All datetimes are stored as UTC and the `<input type=datetime-local>` value is interpreted as UTC. If you expect users in varying timezones, swap this for a per-user TZ preference and convert on render.
- **No recurring events.** One-off events only.
- **No notifications when invited.** Invitees aren't DMed or badge-notified when added to an event. Easy follow-on: on attendee add, insert a DM or a task-like badge row.
- **No per-attendee RSVP status.** Everyone invited is simply "invited." Add a `status` column on `event_attendees` if you want accept/decline.
