# Team Agent

Multi-user team coordinator. Weekend 1: auth + user management.

## Local setup

```bash
# 1. Install Postgres (Mac)
brew install postgresql@16
brew services start postgresql@16
createdb team_agent_dev

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — set SESSION_SECRET to a long random string

# 4. Run migrations
alembic upgrade head

# 5. Seed admin
python seed_admin.py

# 6. Start server
uvicorn app.main:app --reload
# Visit http://localhost:8000
```

## Railway deploy

1. Push repo to GitHub
2. New Railway project → Deploy from GitHub
3. Add PostgreSQL addon (one click)
4. Set env vars: `SESSION_SECRET`, `SECURE_COOKIES=true`
   (`DATABASE_URL` is set automatically by Railway's Postgres addon)
5. Railway runs `Procfile` on deploy — migrations + seed run automatically

## Acceptance test

1. `alembic upgrade head` → three tables created
2. `python seed_admin.py` → admin account created
3. `uvicorn app.main:app --reload` → server starts
4. Visit `localhost:8000` → redirected to `/login`
5. Log in as admin → `/admin/users`
6. Create worker → temp password shown once
7. Toggle permissions → persist on reload
8. Log out, log in as worker → "Hi, nickname" page
9. Worker visits `/admin/users` → 403
