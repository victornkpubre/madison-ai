# Madison (StreamEye)

A TikTok LIVE creator desktop application:

- **`backend/`** — FastAPI + LangGraph server. Multi-agent assistant (onboarding,
  viewer-record capture, audience analysis, idea generation, Telegram/email
  notifications) with Postgres-backed persistence (falls back to in-memory
  storage if `DATABASE_URL` isn't set).
- **`frontend/windows/`** — PyQt5 desktop app (floating button + tray icon)
  that talks to the backend over HTTP/SSE, and captures the TikTok LIVE chat
  off-screen using OpenCV template matching + a Claude vision model.

The backend is cross-platform; the frontend is Windows-only (it uses
`keyboard` and `pygetwindow` for global hotkeys / window detection).

## 1. Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`
- Docker, for the Postgres container (optional — the backend runs fine
  without a database, using in-memory storage instead)
- A Windows machine, only if you want to run `frontend/windows/`

## 2. Configure environment variables

Copy the example and fill in your own keys:

```bash
cp .env.example .env
```

`backend/config.py` reads, at minimum:

```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini        # optional, this is the default
TELEGRAM_BOT_TOKEN=...          # optional, needed for Telegram features
DATABASE_URL=postgresql://streameye:streameye@localhost:5432/streameye   # optional
```

`frontend/windows/app/core/config.py` additionally reads (from the same
`.env`, found by walking up from wherever you launch it):

```
ANTHROPIC_API_KEY=...
VLM_MODEL=claude-haiku-4-5-20251001   # optional, this is the default
```

> **If you're reusing an `.env` you've shared elsewhere (e.g. uploaded it
> somewhere), rotate those keys before deploying anything for real.**

## 3. Start Postgres (optional)

```bash
docker compose up -d
```

This starts the `db` service from `docker-compose.yml` on `localhost:5432`
with user/password/db all set to `streameye`, matching the default
`DATABASE_URL` above. Skip this entirely and leave `DATABASE_URL` unset/blank
if you just want to try the app without persistence.

## 4. Install backend dependencies and run

From the **project root** (imports throughout `backend/` are rooted at
`backend.*`, so this must be run from here, not from inside `backend/`):

```bash
uv sync                 # or: pip install -r requirements.txt
uv run uvicorn backend.main:app --reload
# or, without uv:
uvicorn backend.main:app --reload
```

The API comes up on `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

## 5. Install frontend dependencies and run (Windows)

```bash
cd frontend/windows
pip install -r requirements.txt
python main.py
```

This must be run with `frontend/windows/` as the working directory — it
loads `assets/themes/<theme>.qss` and `config/settings.json` relative to
the current directory.

`config/settings.json` points the floating chat panel at the backend:

```json
{ "agent_url": "http://localhost:8000/chat",
  "resume_url": "http://localhost:8000/resume" }
```

If you're running the backend on a different host/port, update those two
values accordingly.

## Project layout

```
backend/
  domain/          entities + repository interfaces (no framework deps)
  application/      services + LangGraph agents/tools (depend on interfaces only)
  infrastructure/   concrete adapters: SQLAlchemy models/repos, Telegram, email, AI graphs
  interface/        FastAPI routers + Pydantic schemas
  composition.py    wires concrete adapters into the application-layer services
  main.py           FastAPI app + lifespan (DB setup, graph compilation, router mounting)

frontend/windows/
  app/core/         config, local SQLite db, settings.json persistence
  app/ui/           floating button, tray icon, dashboard/chat/home pages
  app/utils/        screen capture (OpenCV + Claude vision), hotkeys, SSE streaming
  main.py           entry point — run from this directory
```
