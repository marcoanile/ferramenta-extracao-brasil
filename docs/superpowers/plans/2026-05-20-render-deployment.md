# Render Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the Nexus Flask app for production deployment on Render with a Persistent Disk for SQLite, file uploads, and runtime credentials.

**Architecture:** Single Render Web Service (Python runtime) running gunicorn → Flask. A 1 GB Persistent Disk is mounted at `/data` and pointed to via `DATA_DIR=/data`. Runtime credentials saved via the UI are written to `/data/.env` and loaded on startup, surviving redeploys.

**Tech Stack:** Python 3, Flask, gunicorn, SQLite, Render Web Service + Persistent Disk, `render.yaml`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `render.yaml` | Declares Render service, env vars, disk |
| Create | `backend/gunicorn.conf.py` | Gunicorn bind/worker config |
| Create | `.gitignore` | Exclude venv, data, .env, pycache |
| Modify | `backend/requirements.txt` | Add gunicorn |
| Modify | `backend/config.py` | Load disk `.env` after project-root `.env` |
| Modify | `backend/app.py` line 90 | Write credentials to `DATA_DIR/.env` not `BASE_DIR/.env` |
| Modify | `backend/app.py` line 604 | Bind to `0.0.0.0` in dev server |

---

### Task 1: Add `.gitignore`

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Create `.gitignore` at the project root**

```
# Python
venv/
__pycache__/
*.pyc
*.pyo
*.pyd
*.egg-info/
dist/
build/

# App data
data/

# Secrets
.env

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 2: Verify venv is not staged**

```bash
git status
```

Expected: `venv/` does not appear in the output (it is ignored).

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

### Task 2: Add gunicorn to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append gunicorn to `backend/requirements.txt`**

Open `backend/requirements.txt` and add this line at the end:

```
gunicorn==22.0.0
```

- [ ] **Step 2: Verify the install works**

```bash
cd backend
pip install -r requirements.txt
```

Expected: `Successfully installed gunicorn-22.0.0` (or "already satisfied" if cached).

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add gunicorn to requirements"
```

---

### Task 3: Create gunicorn config

**Files:**
- Create: `backend/gunicorn.conf.py`

- [ ] **Step 1: Create `backend/gunicorn.conf.py`**

```python
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 2
timeout = 120
```

- [ ] **Step 2: Verify gunicorn can load it**

From the `backend/` directory:

```bash
cd backend
gunicorn app:app -c gunicorn.conf.py --check-config
```

Expected: no output and exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/gunicorn.conf.py
git commit -m "chore: add gunicorn config"
```

---

### Task 4: Fix `config.py` — load disk `.env` on top of project-root `.env`

**Files:**
- Modify: `backend/config.py:1-8`

- [ ] **Step 1: Replace the top of `backend/config.py`**

Replace lines 1–8 (the imports and first `load_dotenv` call + `BASE_DIR`/`DATA_DIR` definitions):

**Before:**
```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
```

**After:**
```python
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent

# Load project-root .env first (local dev defaults)
load_dotenv(BASE_DIR / ".env")

# DATA_DIR comes from real env var (set by Render) or falls back to ../data
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))

# Overlay with disk-persisted .env so runtime-saved credentials survive restarts
_disk_env = DATA_DIR / ".env"
if _disk_env.exists():
    load_dotenv(_disk_env, override=True)
```

- [ ] **Step 2: Verify the module still imports cleanly**

```bash
cd backend
python -c "import config; print('DATA_DIR:', config.DATA_DIR)"
```

Expected output: `DATA_DIR: <path to data directory>` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/config.py
git commit -m "fix: load disk .env overlay in config for Render persistence"
```

---

### Task 5: Fix `app.py` — write credentials to `DATA_DIR/.env`

**Files:**
- Modify: `backend/app.py:90`
- Modify: `backend/app.py:604`

- [ ] **Step 1: Fix the credential write path (line 90)**

**Before (`backend/app.py` line 90):**
```python
    env_path = config.BASE_DIR / ".env"
```

**After:**
```python
    env_path = config.DATA_DIR / ".env"
```

- [ ] **Step 2: Fix the dev server host (line 604)**

**Before (`backend/app.py` line 604):**
```python
    app.run(host="127.0.0.1", port=config.PORT, debug=config.DEBUG)
```

**After:**
```python
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
```

- [ ] **Step 3: Verify the app starts**

```bash
cd backend
python app.py
```

Expected: `Starting Nexus on port 5000` log line and no errors. Press Ctrl+C to stop.

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "fix: write runtime credentials to DATA_DIR and bind dev server to 0.0.0.0"
```

---

### Task 6: Create `render.yaml`

**Files:**
- Create: `render.yaml`

- [ ] **Step 1: Create `render.yaml` at the project root**

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

- [ ] **Step 2: Verify the file is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('render.yaml'))" 2>&1 || python -c "
import sys
with open('render.yaml') as f:
    content = f.read()
print('YAML content:')
print(content)
print('Note: install pyyaml to validate: pip install pyyaml')
"
```

Expected: no errors (or a reminder to install pyyaml — the file content itself is sufficient to verify by eye).

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "feat: add render.yaml for Render deployment with persistent disk"
```

---

### Task 7: End-to-end smoke test

- [ ] **Step 1: Start the app with gunicorn locally**

```bash
cd backend
gunicorn app:app -c gunicorn.conf.py
```

`DATA_DIR` defaults to `../data` (relative to `backend/`), so no env var override needed locally. Expected: gunicorn starts with 2 workers, listening on `0.0.0.0:10000`. No import errors.

- [ ] **Step 2: Check the health endpoint**

In a second terminal:

```bash
curl http://localhost:10000/api/health
```

Expected JSON response:
```json
{"db": "...", "status": "ok", "toconline_authenticated": false, "version": "1.0.0"}
```

- [ ] **Step 3: Check the frontend is served**

```bash
curl -I http://localhost:10000/
```

Expected: `HTTP/1.1 200 OK` with `Content-Type: text/html`.

- [ ] **Step 4: Stop gunicorn (Ctrl+C)**

- [ ] **Step 5: Final commit if any fixes were needed during smoke test**

```bash
git add -p
git commit -m "fix: smoke test corrections"
```

---

## Deployment Checklist (post-implementation)

After pushing to GitHub and connecting to Render:

1. In Render dashboard → New Web Service → connect repo
2. Render auto-detects `render.yaml` — review the service config
3. Set `TOCONLINE_CLIENT_ID` and `TOCONLINE_CLIENT_SECRET` as env vars in the Render dashboard (or leave blank and configure via the app UI after first deploy)
4. Deploy — first deploy provisions the disk at `/data`
5. Visit `<your-render-url>/api/health` to confirm the service is live
