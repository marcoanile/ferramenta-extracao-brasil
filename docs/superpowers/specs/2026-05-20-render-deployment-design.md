# Render Deployment Design

**Date:** 2026-05-20  
**Project:** Nexus Accounting Robot (conversor-brasil)  
**Approach:** Render Web Service + Persistent Disk

---

## Goal

Deploy the Flask backend (which also serves the frontend) to Render as a production web service, with all data (SQLite DB, uploaded files, converted Excel files, logs, runtime credentials) persisted on a Render Disk so nothing is lost across restarts or redeploys.

---

## Architecture

Single Render Web Service running gunicorn → Flask app. A 1 GB Persistent Disk is mounted at `/data`. All mutable state lives on the disk via `DATA_DIR=/data`.

```
Render Web Service (Python runtime)
├── rootDir: backend/
├── build: pip install -r requirements.txt
├── start: gunicorn app:app -c gunicorn.conf.py
└── Persistent Disk mounted at /data
    ├── nexus.db          (SQLite database)
    ├── clients/          (uploaded statements + converted Excel)
    ├── templates/        (Excel templates)
    ├── logs/nexus.log    (app log)
    └── .env              (runtime-saved credentials)
```

---

## Files to Create

### `render.yaml` (project root)

Declares the service, env vars, and disk. Render reads this on deploy.

```yaml
services:
  - type: web
    name: nexus-accounting
    runtime: python
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app -c gunicorn.conf.py
    envVars:
      - key: DATA_DIR
        value: /data
      - key: SECRET_KEY
        generateValue: true
      - key: DEBUG
        value: "false"
      - key: PORT
        value: "10000"
    disk:
      name: nexus-data
      mountPath: /data
      sizeGB: 1
```

### `backend/gunicorn.conf.py`

```python
import os
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 2
timeout = 120
```

### `.gitignore` (project root)

Excludes `venv/`, `data/`, `.env`, `__pycache__`, `.pyc` files.

---

## Files to Modify

### `backend/requirements.txt`

Add `gunicorn` (any recent version, e.g. `gunicorn==22.0.0`).

### `backend/config.py`

Load `.env` from two locations in priority order:
1. `DATA_DIR/.env` — runtime-saved credentials on the disk (takes priority)
2. Project root `.env` — dev-time defaults

`DATA_DIR` is read directly from the OS environment (Render sets it as a real env var, not via `.env`), so it is available before any `.env` loading. `BASE_DIR` must be defined before this block.

```python
# BASE_DIR already defined above as Path(__file__).parent.parent
# Load project root .env first for local dev defaults
load_dotenv(BASE_DIR / ".env")
# Then overlay with disk-persisted .env if present (contains runtime credentials)
_data_dir = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
_disk_env = _data_dir / ".env"
if _disk_env.exists():
    load_dotenv(_disk_env, override=True)
```

### `backend/app.py`

Two changes:

1. **Credential write path** — write to `DATA_DIR / ".env"` instead of `BASE_DIR / ".env"`:
   ```python
   # Before
   env_path = config.BASE_DIR / ".env"
   # After
   env_path = config.DATA_DIR / ".env"
   ```

2. **Dev server host** — change `host="127.0.0.1"` to `host="0.0.0.0"` in the `__main__` block (harmless for prod since gunicorn is used, but correct for any local testing behind a proxy).

---

## Environment Variables on Render

| Variable | Value | Notes |
|---|---|---|
| `DATA_DIR` | `/data` | Points to the persistent disk |
| `SECRET_KEY` | auto-generated | Render generates a random value on first deploy |
| `DEBUG` | `false` | Production mode |
| `PORT` | `10000` | Render's default; gunicorn binds to this |
| `TOCONLINE_CLIENT_ID` | *(set via UI)* | Saved to `/data/.env` at runtime |
| `TOCONLINE_CLIENT_SECRET` | *(set via UI)* | Saved to `/data/.env` at runtime |

---

## Data Persistence

- SQLite DB, uploaded files, and converted Excel files all live under `DATA_DIR=/data` — the persistent disk.
- Runtime credentials saved via the UI are written to `/data/.env` and loaded on startup.
- No database migration needed; SQLAlchemy creates tables on first run.

---

## Out of Scope

- Migrating SQLite to PostgreSQL
- Moving file uploads to S3/R2
- Docker containerisation
- Authentication/authorization for the web UI
