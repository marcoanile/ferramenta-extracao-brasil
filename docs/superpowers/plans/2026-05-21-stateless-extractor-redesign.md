# Stateless Extractor Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bloated multi-view SaaS shell with a focused two-tab tool — a stateless PDF→Excel converter and a consolidation workspace backed by a minimal SQLite database.

**Architecture:** Flask serves a single HTML page with two tabs. The `/convert` endpoint is fully stateless (file in, Excel attachment out, nothing persisted). The `/api/groups/*` endpoints back the Consolidar tab with a three-table SQLite schema (groups → extracts → movements). All parsers and `template_engine.py` are left untouched.

**Tech Stack:** Python 3.11+, Flask 3, SQLite (plain `sqlite3` module), openpyxl, Vanilla JS, CSS custom properties.

**Note on tests:** The project has no test suite. Verification steps use `curl` smoke tests against the running server.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Delete | `backend/api/` | TOConline + Cegid clients — removed entirely |
| Delete | `backend/reconciliation/` | Reconciliation engine — removed entirely |
| Delete | `backend/storage/file_store.py` | Old file store — removed |
| Rewrite | `backend/config.py` | Strip TOConline/Cegid vars; add `TEMP_DIR` |
| Rewrite | `backend/storage/database.py` | New minimal sqlite3 schema + query functions |
| Rewrite | `backend/app.py` | 10 routes only; imports from new DB module |
| Rewrite | `frontend/index.html` | Two-tab layout, no sidebar, no auth modal |
| Rewrite | `frontend/static/css/style.css` | New focused styles, keep design tokens |
| Rewrite | `frontend/static/js/app.js` | Converter + Consolidar tab logic |
| Keep | `backend/parsers/` | All bank parsers — untouched |
| Keep | `backend/converter/template_engine.py` | Excel generation — untouched |

---

## Task 1: Delete removed modules

**Files:**
- Delete: `backend/api/` (entire folder)
- Delete: `backend/reconciliation/` (entire folder)
- Delete: `backend/storage/file_store.py`

- [ ] **Step 1: Delete the three paths**

```powershell
Remove-Item -Recurse -Force "backend\api"
Remove-Item -Recurse -Force "backend\reconciliation"
Remove-Item -Force "backend\storage\file_store.py"
```

- [ ] **Step 2: Verify they are gone**

```powershell
Test-Path "backend\api"           # must print False
Test-Path "backend\reconciliation" # must print False
Test-Path "backend\storage\file_store.py" # must print False
```

Expected output: three lines of `False`.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete api/, reconciliation/, file_store — not needed in focused tool"
```

---

## Task 2: Rewrite `backend/config.py`

**Files:**
- Modify: `backend/config.py`

Removes: `TOCONLINE_*`, `CEGID_*`, `CLIENTS_DIR` vars.
Adds: `TEMP_DIR`.
Keeps: seed mechanism (copies template files from `backend/seed/` on first boot).

- [ ] **Step 1: Overwrite `backend/config.py` with the trimmed version**

```python
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
SEED_DIR = Path(__file__).parent / "seed"

SECRET_KEY = os.getenv("SECRET_KEY", "nexus-accounting-secret")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

TEMPLATES_DIR = DATA_DIR / "templates"
LOGS_DIR = DATA_DIR / "logs"
TEMP_DIR = DATA_DIR / "temp"
DB_PATH = DATA_DIR / "nexus.db"

SUPPORTED_FORMATS = [".pdf", ".xlsx", ".xls", ".csv"]

for d in [DATA_DIR, TEMPLATES_DIR, LOGS_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Copy bundled template into the templates dir on first boot (e.g. Render fresh disk).
if SEED_DIR.exists():
    for seed_file in SEED_DIR.glob("*"):
        target = TEMPLATES_DIR / seed_file.name
        if not target.exists():
            shutil.copy2(seed_file, target)
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd backend && python -c "import config; print(config.TEMP_DIR, config.DB_PATH)"
```

Expected: two valid paths printed, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/config.py
git commit -m "chore: strip TOConline/Cegid vars from config; add TEMP_DIR"
```

---

## Task 3: Rewrite `backend/storage/database.py`

**Files:**
- Modify: `backend/storage/database.py`

Replaces the SQLAlchemy ORM with plain `sqlite3`. New schema: `groups`, `extracts`, `movements` with `ON DELETE CASCADE` foreign keys.

- [ ] **Step 1: Overwrite `backend/storage/database.py`**

```python
import sqlite3
from datetime import datetime
import config


def _conn():
    con = sqlite3.connect(str(config.DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS extracts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id       INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                filename       TEXT,
                bank_name      TEXT,
                period_start   TEXT,
                period_end     TEXT,
                movement_count INTEGER,
                added_at       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS movements (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                extract_id   INTEGER NOT NULL REFERENCES extracts(id) ON DELETE CASCADE,
                group_id     INTEGER NOT NULL,
                date         TEXT,
                description  TEXT,
                amount       REAL,
                balance      REAL
            );
        """)


def get_groups() -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT g.id, g.name, g.created_at, COUNT(e.id) AS extract_count
            FROM groups g
            LEFT JOIN extracts e ON e.group_id = g.id
            GROUP BY g.id
            ORDER BY g.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_group(group_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    return dict(row) if row else None


def create_group(name: str) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO groups (name, created_at) VALUES (?, ?)",
            (name, datetime.now().isoformat()),
        )
        return cur.lastrowid


def delete_group(group_id: int):
    with _conn() as con:
        con.execute("DELETE FROM groups WHERE id = ?", (group_id,))


def get_extracts(group_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM extracts WHERE group_id = ?
               ORDER BY period_start ASC, added_at ASC""",
            (group_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_extract(group_id: int, filename: str, bank_name: str,
                period_start: str, period_end: str, movement_count: int) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO extracts (group_id, filename, bank_name, period_start,
               period_end, movement_count, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (group_id, filename, bank_name, period_start, period_end,
             movement_count, datetime.now().isoformat()),
        )
        return cur.lastrowid


def delete_extract(extract_id: int):
    with _conn() as con:
        con.execute("DELETE FROM extracts WHERE id = ?", (extract_id,))


def add_movements(extract_id: int, group_id: int, movements: list[dict]):
    with _conn() as con:
        con.executemany(
            """INSERT INTO movements (extract_id, group_id, date, description, amount, balance)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (extract_id, group_id,
                 m["date"], m["description"], m["amount"], m.get("balance"))
                for m in movements
            ],
        )


def get_movements_for_group(group_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM movements WHERE group_id = ?
               ORDER BY date ASC, id ASC""",
            (group_id,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Verify `init_db` creates the tables**

```bash
cd backend && python -c "
import config, storage.database as db
db.init_db()
gid = db.create_group('test')
print('group id:', gid)
print('groups:', db.get_groups())
db.delete_group(gid)
print('after delete:', db.get_groups())
"
```

Expected: prints a group id, then `[{'id': 1, 'name': 'test', ...}]`, then `[]`.

- [ ] **Step 3: Commit**

```bash
git add backend/storage/database.py
git commit -m "feat: new minimal sqlite3 DB module (groups/extracts/movements)"
```

---

## Task 4: Rewrite `backend/app.py`

**Files:**
- Modify: `backend/app.py`

10 routes. The `_build_consolidated_excel` helper consolidates the merged-Excel logic that previously lived inline. `after_this_request` cleans up temp files after Flask streams the response.

- [ ] **Step 1: Overwrite `backend/app.py`**

```python
"""Nexus Extrator — Flask backend."""
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, after_this_request, request, jsonify, send_file
from flask_cors import CORS

import config
from storage.database import (
    init_db, get_groups, get_group, create_group, delete_group,
    get_extracts, add_extract, delete_extract, add_movements,
    get_movements_for_group,
)
from parsers.pdf_parser import parse_pdf
from parsers.excel_parser import parse_excel
from parsers.csv_parser import parse_csv
from converter.template_engine import (
    fill_template, _find_template, _find_header_row, _find_balance_rows, _to_date,
)

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOGS_DIR / "nexus.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("nexus")

app = Flask(__name__, static_folder="../frontend/static", static_url_path="/static")
app.secret_key = config.SECRET_KEY
CORS(app, origins="*")

init_db()


@app.route("/")
def index():
    return send_file("../frontend/index.html")


def _parse_file(file_path: Path, suffix: str):
    if suffix == ".pdf":
        return parse_pdf(file_path, "")
    if suffix in (".xlsx", ".xls"):
        return parse_excel(file_path, "")
    if suffix == ".csv":
        return parse_csv(file_path, "")
    raise ValueError(f"Formato não suportado: {suffix}")


# ── Stateless converter ───────────────────────────────────────────────────────

@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "Ficheiro em falta"}), 400
    file = request.files["file"]
    suffix = Path(file.filename).suffix.lower()
    if suffix not in config.SUPPORTED_FORMATS:
        return jsonify({"error": f"Formato não suportado: {suffix}"}), 400

    tmp = config.TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
    out = config.TEMP_DIR / f"extrato_{uuid.uuid4().hex[:8]}.xlsx"
    file.save(str(tmp))

    try:
        parsed = _parse_file(tmp, suffix)
        movements = parsed.sorted_movements()
        year = int(parsed.period_start[:4]) if parsed.period_start else datetime.now().year
        fill_template(statement=parsed, output_path=out, client_name="", year=year)

        bank_slug = (parsed.bank_name or "extrato").lower().replace(" ", "_").replace("/", "-")
        download_name = f"extrato_{bank_slug}_{year}.xlsx"

        @after_this_request
        def _cleanup(response):
            tmp.unlink(missing_ok=True)
            out.unlink(missing_ok=True)
            return response

        response = send_file(str(out), as_attachment=True, download_name=download_name)
        response.headers["X-Bank-Name"] = parsed.bank_name or ""
        response.headers["X-Movement-Count"] = str(len(movements))
        response.headers["X-Period-Start"] = parsed.period_start or ""
        response.headers["X-Period-End"] = parsed.period_end or ""
        return response

    except Exception as e:
        log.exception("Conversion error")
        tmp.unlink(missing_ok=True)
        if out.exists():
            out.unlink()
        return jsonify({"error": str(e)}), 500


# ── Consolidation groups ──────────────────────────────────────────────────────

@app.route("/api/groups", methods=["GET"])
def list_groups():
    return jsonify({"data": get_groups()})


@app.route("/api/groups", methods=["POST"])
def create_group_route():
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    gid = create_group(name)
    return jsonify({"id": gid, "name": name}), 201


@app.route("/api/groups/<int:group_id>", methods=["DELETE"])
def delete_group_route(group_id: int):
    if not get_group(group_id):
        return jsonify({"error": "Grupo não encontrado"}), 404
    delete_group(group_id)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/extracts", methods=["GET"])
def list_extracts(group_id: int):
    if not get_group(group_id):
        return jsonify({"error": "Grupo não encontrado"}), 404
    return jsonify({"data": get_extracts(group_id)})


@app.route("/api/groups/<int:group_id>/upload", methods=["POST"])
def upload_to_group(group_id: int):
    if not get_group(group_id):
        return jsonify({"error": "Grupo não encontrado"}), 404
    if "file" not in request.files:
        return jsonify({"error": "Ficheiro em falta"}), 400
    file = request.files["file"]
    suffix = Path(file.filename).suffix.lower()
    if suffix not in config.SUPPORTED_FORMATS:
        return jsonify({"error": f"Formato não suportado: {suffix}"}), 400

    tmp = config.TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
    file.save(str(tmp))

    try:
        parsed = _parse_file(tmp, suffix)
        movements = parsed.sorted_movements()
        extract_id = add_extract(
            group_id=group_id,
            filename=file.filename,
            bank_name=parsed.bank_name,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
            movement_count=len(movements),
        )
        add_movements(extract_id, group_id, [
            {"date": m.date, "description": m.description,
             "amount": m.amount, "balance": m.balance}
            for m in movements
        ])
        return jsonify({
            "extract_id": extract_id,
            "bank_name": parsed.bank_name,
            "period_start": parsed.period_start,
            "period_end": parsed.period_end,
            "movement_count": len(movements),
        }), 201

    except Exception as e:
        log.exception("Upload-to-group error")
        return jsonify({"error": str(e)}), 500
    finally:
        tmp.unlink(missing_ok=True)


@app.route("/api/groups/<int:group_id>/extracts/<int:extract_id>", methods=["DELETE"])
def delete_extract_route(group_id: int, extract_id: int):
    delete_extract(extract_id)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/generate")
def generate_group(group_id: int):
    group = get_group(group_id)
    if not group:
        return jsonify({"error": "Grupo não encontrado"}), 404
    movements = get_movements_for_group(group_id)
    if not movements:
        return jsonify({"error": "Sem movimentos para consolidar"}), 400

    out = config.TEMP_DIR / f"consolidado_{uuid.uuid4().hex[:8]}.xlsx"
    try:
        _build_consolidated_excel(movements, out)
        safe_name = group["name"].replace(" ", "_").replace("/", "-")

        @after_this_request
        def _cleanup(response):
            out.unlink(missing_ok=True)
            return response

        return send_file(str(out), as_attachment=True, download_name=f"{safe_name}.xlsx")

    except Exception as e:
        log.exception("Generate error")
        if out.exists():
            out.unlink()
        return jsonify({"error": str(e)}), 500


def _build_consolidated_excel(movements: list[dict], out: Path):
    import shutil
    import openpyxl
    from openpyxl.styles import Border, Side

    thin = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    template = _find_template(None)

    if template:
        shutil.copy2(str(template), str(out))
        wb = openpyxl.load_workbook(str(out))
        ws = wb.active
        header_row = _find_header_row(ws)
        ini_row, fin_row = _find_balance_rows(ws)
        data_start = header_row + 1

        opening = next((m["balance"] for m in movements if m["balance"] is not None), 0) or 0
        movement_sum = round(sum(m["amount"] for m in movements), 2)
        effective_closing = round(opening + movement_sum, 2)

        if ini_row:
            ws.cell(row=ini_row, column=4).value = opening
        if fin_row:
            ws.cell(row=fin_row, column=4).value = effective_closing

        for row_idx in range(data_start, ws.max_row + 1):
            for col in range(1, ws.max_column + 1):
                ws.cell(row=row_idx, column=col).value = None

        for i, mov in enumerate(movements):
            row = data_start + i
            d = _to_date(mov["date"])
            ws.cell(row=row, column=1, value=d).number_format = "DD/MM/YYYY"
            ws.cell(row=row, column=1).border = thin
            ws.cell(row=row, column=2, value=d).number_format = "DD/MM/YYYY"
            ws.cell(row=row, column=2).border = thin
            ws.cell(row=row, column=3, value=mov.get("description") or "").border = thin
            cell = ws.cell(row=row, column=4, value=mov["amount"])
            cell.number_format = "#,##0.00"
            cell.border = thin
        wb.save(str(out))
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Movimentos"
        ws.append(["Data Mov.", "Data Valor", "Descrição do Movimento", "Movimento"])
        for mov in movements:
            d = _to_date(mov["date"])
            ws.append([d, d, mov.get("description") or "", mov["amount"]])
        wb.save(str(out))


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    log.info("Starting Nexus on port %d", config.PORT)
    app.run(host="127.0.0.1", port=config.PORT, debug=config.DEBUG)
```

- [ ] **Step 2: Verify the app starts cleanly**

```bash
cd backend && python app.py
```

Expected: `Starting Nexus on port 5000` — no import errors, no tracebacks.  
Stop with Ctrl+C.

- [ ] **Step 3: Smoke test health endpoint**

With the server running in another terminal:

```bash
curl http://localhost:5000/api/health
```

Expected: `{"status": "ok"}`

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat: rewrite app.py — 10 focused routes, stateless converter + groups API"
```

---

## Task 5: Rewrite `frontend/index.html`

**Files:**
- Modify: `frontend/index.html`

No sidebar. No auth modal. No upload modal. Just header + tabs + content area + toast container.

- [ ] **Step 1: Overwrite `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nexus Extrator</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div id="app">

  <header id="topbar">
    <div class="brand">
      <img src="/static/img/logo.png" alt="Nexus" class="logo">
      <span class="brand-name">Nexus <span class="brand-accent">Extrator</span></span>
    </div>
    <button id="theme-toggle" onclick="toggleTheme()" aria-label="Alternar tema"></button>
  </header>

  <nav id="tabs">
    <button class="tab active" data-tab="converter" onclick="switchTab('converter')">Converter</button>
    <button class="tab" data-tab="consolidar" onclick="switchTab('consolidar')">Consolidar</button>
  </nav>

  <main id="content"></main>

</div>

<div id="toast-container"></div>

<script src="/static/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify the page loads in the browser**

Start the server (`python backend/app.py`) and open `http://localhost:5000`. The page should load without JS errors in the browser console (JS is written in Task 7, so expect a blank content area at this step).

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: new index.html — two-tab layout, no sidebar, no modals"
```

---

## Task 6: Rewrite `frontend/static/css/style.css`

**Files:**
- Modify: `frontend/static/css/style.css`

Keeps dark/light design tokens and button styles. New styles for: tabs, drop zone, progress bar, result card, consolidar two-panel layout, extracts table, toasts.

- [ ] **Step 1: Overwrite `frontend/static/css/style.css`**

```css
/* ── Design tokens ──────────────────────────────────────────── */
:root {
  --primary: #f0b429;
  --primary-light: #f5c842;
  --success: #3fb950;
  --danger: #f85149;
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #1c2128;
  --border: rgba(255,255,255,.08);
  --border-solid: #30363d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --radius: 8px;
  --shadow: 0 1px 4px rgba(0,0,0,.4);
  --shadow-md: 0 4px 16px rgba(0,0,0,.5);
}

[data-theme="light"] {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --surface2: #eef0f4;
  --border: rgba(0,0,0,.1);
  --border-solid: #d0d7de;
  --text: #1c2128;
  --text-muted: #57606a;
  --shadow: 0 1px 4px rgba(0,0,0,.1);
  --shadow-md: 0 4px 16px rgba(0,0,0,.15);
}

/* ── Base ───────────────────────────────────────────────────── */
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; color: var(--text); background: var(--bg); }
#app { display: flex; flex-direction: column; min-height: 100vh; }

/* ── Header ─────────────────────────────────────────────────── */
#topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 32px; height: 60px; flex-shrink: 0;
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 10px; }
.logo { height: 30px; width: auto; }
.brand-name { font-size: 17px; font-weight: 700; letter-spacing: -.3px; }
.brand-accent { color: var(--primary); }

#theme-toggle {
  background: none; border: 1px solid var(--border-solid); border-radius: 6px;
  color: var(--text-muted); cursor: pointer; font-size: 16px; line-height: 1;
  padding: 5px 9px; transition: background .15s, color .15s;
}
#theme-toggle:hover { background: var(--surface2); color: var(--text); }

/* ── Tabs ───────────────────────────────────────────────────── */
#tabs {
  display: flex; padding: 0 32px; flex-shrink: 0;
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.tab {
  background: none; border: none; border-bottom: 2px solid transparent;
  color: var(--text-muted); cursor: pointer; font-size: 14px; font-weight: 500;
  padding: 12px 20px; transition: color .15s, border-color .15s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); }

/* ── Main content ───────────────────────────────────────────── */
#content { flex: 1; padding: 40px 32px; overflow-y: auto; }

/* ── Buttons ────────────────────────────────────────────────── */
.btn {
  border: none; border-radius: 6px; cursor: pointer; font-size: 13px;
  font-weight: 500; padding: 9px 18px; transition: opacity .15s, background .15s;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-primary { background: var(--primary); color: #0d1117; }
.btn-primary:hover:not(:disabled) { background: var(--primary-light); }
.btn-outline { background: transparent; border: 1px solid var(--border-solid); color: var(--text); }
.btn-outline:hover:not(:disabled) { background: var(--surface2); }
.btn-danger { background: var(--danger); color: #fff; }
.btn-danger:hover:not(:disabled) { opacity: .85; }
.btn-sm { font-size: 12px; padding: 5px 12px; }
.btn-icon { background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 15px; padding: 4px 6px; border-radius: 4px; }
.btn-icon:hover { background: var(--surface2); color: var(--text); }

/* ── Drop zone ──────────────────────────────────────────────── */
.drop-zone {
  border: 2px dashed var(--border-solid); border-radius: 12px;
  padding: 52px 32px; text-align: center; cursor: pointer;
  transition: border-color .2s, background .2s; background: var(--surface);
}
.drop-zone:hover, .drop-zone.drag { border-color: var(--primary); background: var(--surface2); }
.dz-icon { font-size: 42px; margin-bottom: 14px; }
.dz-title { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
.dz-sub { color: var(--text-muted); font-size: 13px; }

/* ── Bank chips ─────────────────────────────────────────────── */
.bank-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 18px; justify-content: center; }
.chip {
  background: var(--surface2); border: 1px solid var(--border-solid);
  border-radius: 20px; color: var(--text-muted); font-size: 11px; padding: 3px 11px;
}

/* ── Converter wrapper ──────────────────────────────────────── */
.converter-wrap { max-width: 560px; margin: 0 auto; }
.converter-hero { margin-bottom: 28px; }
.converter-hero h2 { font-size: 22px; font-weight: 700; margin-bottom: 8px; }
.converter-hero p { color: var(--text-muted); line-height: 1.65; font-size: 14px; }

/* ── Progress ───────────────────────────────────────────────── */
.progress-wrap { padding: 24px 0; }
.progress-label { font-size: 14px; font-weight: 600; margin-bottom: 16px; }
.progress-bar { background: var(--surface2); border-radius: 4px; height: 6px; overflow: hidden; }
.progress-fill {
  height: 100%; background: var(--primary); border-radius: 4px;
  width: 35%; animation: indeterminate 1.2s ease-in-out infinite;
}
@keyframes indeterminate { 0% { margin-left: -35%; } 100% { margin-left: 100%; } }
.progress-sub { color: var(--text-muted); font-size: 13px; margin-top: 10px; }

/* ── Result card ────────────────────────────────────────────── */
.result-card {
  background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 12px; padding: 32px; margin-top: 4px;
}
.result-card.error { border-color: var(--danger); }
.result-icon { font-size: 34px; margin-bottom: 12px; }
.result-title { font-size: 18px; font-weight: 700; margin-bottom: 6px; }
.result-meta { color: var(--text-muted); font-size: 13px; margin-bottom: 24px; line-height: 1.6; }
.result-meta.error-text { color: var(--danger); font-family: monospace; font-size: 12px; }
.result-actions { display: flex; gap: 10px; flex-wrap: wrap; }

/* ── Consolidar layout ──────────────────────────────────────── */
.consolidar-wrap {
  display: flex; gap: 20px;
  height: calc(100vh - 141px); /* viewport minus header + tabs + content padding */
}

.groups-panel {
  width: 230px; flex-shrink: 0; background: var(--surface);
  border: 1px solid var(--border-solid); border-radius: 10px;
  display: flex; flex-direction: column; overflow: hidden;
}
.groups-panel-header {
  padding: 12px 14px; border-bottom: 1px solid var(--border);
  font-weight: 600; font-size: 13px; display: flex;
  align-items: center; justify-content: space-between; flex-shrink: 0;
}
.groups-list { flex: 1; overflow-y: auto; }
.group-item {
  padding: 10px 14px; cursor: pointer;
  border-left: 3px solid transparent; transition: background .1s;
}
.group-item:hover { background: var(--surface2); }
.group-item.active { background: var(--surface2); border-left-color: var(--primary); }
.group-item-name { font-weight: 500; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.group-item-meta { color: var(--text-muted); font-size: 11px; margin-top: 2px; }

.new-group-form { display: flex; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--border); }
.new-group-form input {
  flex: 1; background: var(--surface2); border: 1px solid var(--border-solid);
  border-radius: 4px; color: var(--text); font-size: 13px; padding: 5px 8px; outline: none;
}
.new-group-form input:focus { border-color: var(--primary); }

.group-workspace {
  flex: 1; background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 10px; display: flex; flex-direction: column; overflow: hidden;
}
.workspace-header {
  padding: 14px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
}
.workspace-title { font-size: 16px; font-weight: 700; }
.workspace-actions { display: flex; gap: 8px; align-items: center; }
.workspace-body { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }

.workspace-drop {
  border: 2px dashed var(--border-solid); border-radius: 8px;
  padding: 20px; text-align: center; cursor: pointer;
  transition: border-color .2s, background .2s; flex-shrink: 0;
}
.workspace-drop:hover, .workspace-drop.drag { border-color: var(--primary); background: var(--surface2); }
.workspace-drop p { color: var(--text-muted); font-size: 13px; }
.workspace-drop p + p { margin-top: 4px; font-size: 12px; }

/* ── Table ──────────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th { color: var(--text-muted); font-size: 12px; font-weight: 600; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: middle; }
tr:last-child td { border-bottom: none; }

/* ── Empty state ────────────────────────────────────────────── */
.empty-state { padding: 48px 24px; text-align: center; color: var(--text-muted); }
.empty-state .es-icon { font-size: 32px; margin-bottom: 10px; }
.empty-state p { line-height: 1.6; font-size: 13px; }

/* ── Toast ──────────────────────────────────────────────────── */
#toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast {
  background: var(--surface); border: 1px solid var(--border-solid);
  border-radius: 8px; box-shadow: var(--shadow-md); color: var(--text);
  font-size: 13px; max-width: 320px; padding: 12px 16px;
  animation: slide-in .2s ease; pointer-events: auto;
}
.toast.success { border-left: 3px solid var(--success); }
.toast.error   { border-left: 3px solid var(--danger); }
.toast.info    { border-left: 3px solid var(--primary); }
@keyframes slide-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

/* ── Misc helpers ───────────────────────────────────────────── */
.text-muted { color: var(--text-muted); }
.text-sm { font-size: 12px; }
.mt-4 { margin-top: 4px; }
.mt-8 { margin-top: 8px; }
```

- [ ] **Step 2: Verify styles load in browser**

Reload `http://localhost:5000` and confirm the header, tabs, and theme toggle are styled.

- [ ] **Step 3: Commit**

```bash
git add frontend/static/css/style.css
git commit -m "feat: new focused CSS — two-tab layout, drop zone, result card, consolidar panels"
```

---

## Task 7: Rewrite `frontend/static/js/app.js`

**Files:**
- Modify: `frontend/static/js/app.js`

Two self-contained sections: Converter and Consolidar. State is minimal — no router, just two tab renderers. The converter uses a closure-scoped `converterBlob` to hold the response for re-download. The consolidar section holds `activeGroupId` and `groupExtracts` in module-level vars.

- [ ] **Step 1: Overwrite `frontend/static/js/app.js`**

```javascript
/* Nexus Extrator */
'use strict';

// ── Theme ──────────────────────────────────────────────────────────────────
function initTheme() {
  applyTheme(localStorage.getItem('nexus-theme') || 'dark');
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  applyTheme(next);
  localStorage.setItem('nexus-theme', next);
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '☀' : '🌙';
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ── Escape HTML ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Format period ──────────────────────────────────────────────────────────
function fmtPeriod(start, end) {
  const fmt = s => s ? s.slice(0, 10).split('-').reverse().join('/') : '?';
  if (!start && !end) return '—';
  return `${fmt(start)} → ${fmt(end)}`;
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(el =>
    el.classList.toggle('active', el.dataset.tab === tab));
  if (tab === 'converter') renderConverter();
  else renderConsolidar();
}

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  renderConverter();
});

// ══════════════════════════════════════════════════════════════════════════
// CONVERTER TAB
// ══════════════════════════════════════════════════════════════════════════

const BANKS = [
  'Millennium BCP', 'BPI', 'CGD', 'Santander',
  'Novo Banco', 'Bankinter', 'Crédito Agrícola',
];

let converterBlob = null;
let converterFilename = 'extrato.xlsx';

function renderConverter() {
  document.getElementById('content').innerHTML = `
    <div class="converter-wrap">
      <div class="converter-hero">
        <h2>Converter extrato bancário</h2>
        <p>Arraste um ficheiro PDF, Excel ou CSV. Recebe de imediato o Excel pronto a importar no TOConline.</p>
      </div>
      <div id="converter-body"></div>
    </div>`;
  showConverterIdle();
}

function showConverterIdle() {
  document.getElementById('converter-body').innerHTML = `
    <div class="drop-zone" id="conv-drop" onclick="document.getElementById('conv-file').click()">
      <div class="dz-icon">📄</div>
      <div class="dz-title">Clique ou arraste o ficheiro aqui</div>
      <div class="dz-sub">PDF · XLSX · XLS · CSV</div>
    </div>
    <input type="file" id="conv-file" accept=".pdf,.xlsx,.xls,.csv"
           style="display:none" onchange="handleConverterFile(event)">
    <div class="bank-chips">
      ${BANKS.map(b => `<span class="chip">${esc(b)}</span>`).join('')}
    </div>`;

  const zone = document.getElementById('conv-drop');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag');
    const f = e.dataTransfer.files[0];
    if (f) uploadConverter(f);
  });
}

function handleConverterFile(e) {
  const f = e.target.files[0];
  if (f) uploadConverter(f);
}

function showConverterProcessing(filename) {
  document.getElementById('converter-body').innerHTML = `
    <div class="progress-wrap">
      <div class="progress-label">A processar <em>${esc(filename)}</em>…</div>
      <div class="progress-bar"><div class="progress-fill"></div></div>
      <div class="progress-sub">A detectar banco e extrair movimentos…</div>
    </div>`;
}

function showConverterDone(bankName, movCount, periodStart, periodEnd) {
  const period = fmtPeriod(periodStart, periodEnd);
  document.getElementById('converter-body').innerHTML = `
    <div class="result-card">
      <div class="result-icon">✅</div>
      <div class="result-title">Extrato convertido com sucesso</div>
      <div class="result-meta">
        ${esc(bankName || 'Banco detectado')}
        ${movCount ? ` · ${esc(movCount)} movimentos` : ''}
        ${period !== '—' ? `<br>${period}` : ''}
      </div>
      <div class="result-actions">
        <button class="btn btn-primary" onclick="downloadConverterFile()">⬇ Descarregar Excel</button>
        <button class="btn btn-outline" onclick="showConverterIdle()">Converter outro ficheiro</button>
      </div>
    </div>`;
}

function showConverterError(msg) {
  document.getElementById('converter-body').innerHTML = `
    <div class="result-card error">
      <div class="result-icon">❌</div>
      <div class="result-title">Erro ao converter</div>
      <div class="result-meta error-text">${esc(msg)}</div>
      <div class="result-actions">
        <button class="btn btn-outline" onclick="showConverterIdle()">Tentar novamente</button>
      </div>
    </div>`;
}

async function uploadConverter(file) {
  showConverterProcessing(file.name);
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/convert', { method: 'POST', body: fd });
    if (!r.ok) {
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      showConverterError(d.error || 'Erro desconhecido');
      return;
    }
    const bankName  = r.headers.get('X-Bank-Name') || '';
    const movCount  = r.headers.get('X-Movement-Count') || '';
    const periodStart = r.headers.get('X-Period-Start') || '';
    const periodEnd   = r.headers.get('X-Period-End') || '';

    const cd = r.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename[^;=\n]*=["']?([^"';\n]+)/);
    converterFilename = match ? match[1] : 'extrato.xlsx';
    converterBlob = await r.blob();

    showConverterDone(bankName, movCount, periodStart, periodEnd);
    downloadConverterFile();
  } catch (e) {
    showConverterError(e.message);
  }
}

function downloadConverterFile() {
  if (!converterBlob) return;
  const url = URL.createObjectURL(converterBlob);
  const a = Object.assign(document.createElement('a'), { href: url, download: converterFilename });
  a.click();
  URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════════════════════════
// CONSOLIDAR TAB
// ══════════════════════════════════════════════════════════════════════════

let groups = [];
let activeGroupId = null;
let groupExtracts = [];

async function renderConsolidar() {
  await loadGroups();
  document.getElementById('content').innerHTML = `
    <div class="consolidar-wrap">
      <div class="groups-panel">
        <div class="groups-panel-header">
          <span>Grupos</span>
          <button class="btn btn-sm btn-outline" onclick="showNewGroupForm()">+ Novo</button>
        </div>
        <div id="groups-list" class="groups-list"></div>
      </div>
      <div class="group-workspace" id="group-workspace">
        <div class="empty-state">
          <div class="es-icon">📂</div>
          <p>Selecione um grupo ou crie um novo<br>para começar a consolidar extratos.</p>
        </div>
      </div>
    </div>`;
  renderGroupsList();
  if (activeGroupId) await loadGroupWorkspace(activeGroupId);
}

async function loadGroups() {
  try {
    const r = await fetch('/api/groups');
    const d = await r.json();
    groups = d.data || [];
  } catch (e) {
    groups = [];
  }
}

function renderGroupsList() {
  const el = document.getElementById('groups-list');
  if (!el) return;
  if (!groups.length) {
    el.innerHTML = '<div class="empty-state" style="padding:20px 14px"><p>Sem grupos ainda</p></div>';
    return;
  }
  el.innerHTML = groups.map(g => `
    <div class="group-item ${g.id === activeGroupId ? 'active' : ''}"
         onclick="selectGroup(${g.id})">
      <div class="group-item-name">${esc(g.name)}</div>
      <div class="group-item-meta">${g.extract_count} extrato${g.extract_count !== 1 ? 's' : ''}</div>
    </div>`).join('');
}

function showNewGroupForm() {
  const list = document.getElementById('groups-list');
  if (!list || document.getElementById('new-group-input')) return;
  const form = document.createElement('div');
  form.className = 'new-group-form';
  form.innerHTML = `
    <input type="text" id="new-group-input" placeholder="Nome do grupo" maxlength="80">
    <button class="btn btn-sm btn-primary" onclick="confirmNewGroup()">✓</button>`;
  list.prepend(form);
  const input = document.getElementById('new-group-input');
  input.focus();
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmNewGroup();
    if (e.key === 'Escape') form.remove();
  });
}

async function confirmNewGroup() {
  const input = document.getElementById('new-group-input');
  if (!input) return;
  const name = input.value.trim();
  if (!name) return;
  try {
    const r = await fetch('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    activeGroupId = d.id;
    await renderConsolidar();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function selectGroup(id) {
  activeGroupId = id;
  renderGroupsList();
  await loadGroupWorkspace(id);
}

async function loadGroupWorkspace(id) {
  const group = groups.find(g => g.id === id);
  if (!group) return;
  try {
    const r = await fetch(`/api/groups/${id}/extracts`);
    const d = await r.json();
    groupExtracts = d.data || [];
  } catch (e) {
    groupExtracts = [];
  }
  renderWorkspace(group);
}

function renderWorkspace(group) {
  const ws = document.getElementById('group-workspace');
  if (!ws) return;
  ws.innerHTML = `
    <div class="workspace-header">
      <span class="workspace-title">${esc(group.name)}</span>
      <div class="workspace-actions">
        <button class="btn btn-primary btn-sm" onclick="generateGroup(${group.id})">
          ⬇ Gerar Excel Consolidado
        </button>
        <button class="btn-icon" title="Eliminar grupo" onclick="confirmDeleteGroup(${group.id})">🗑</button>
      </div>
    </div>
    <div class="workspace-body">
      <div class="workspace-drop" id="ws-drop"
           onclick="document.getElementById('ws-file').click()">
        <p>📥 Arraste um extrato para adicionar ao grupo</p>
        <p>PDF · XLSX · XLS · CSV</p>
      </div>
      <input type="file" id="ws-file" accept=".pdf,.xlsx,.xls,.csv" style="display:none"
             onchange="handleWorkspaceFile(event, ${group.id})">
      <div id="extracts-table">${renderExtractsTable(group.id)}</div>
    </div>`;

  const drop = document.getElementById('ws-drop');
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('drag');
    const f = e.dataTransfer.files[0];
    if (f) uploadToGroup(group.id, f);
  });
}

function renderExtractsTable(groupId) {
  if (!groupExtracts.length) {
    return `<div class="empty-state">
      <div class="es-icon">📭</div>
      <p>Ainda sem extratos.<br>Arraste um ficheiro para começar.</p>
    </div>`;
  }
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Banco</th><th>Período</th><th>Movimentos</th><th></th></tr>
        </thead>
        <tbody>
          ${groupExtracts.map(e => `
            <tr>
              <td>${esc(e.bank_name || '—')}</td>
              <td class="text-muted">${esc(fmtPeriod(e.period_start, e.period_end))}</td>
              <td>${esc(e.movement_count ?? '—')}</td>
              <td>
                <button class="btn-icon" title="Remover extrato"
                        onclick="removeExtract(${groupId}, ${e.id})">🗑</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function handleWorkspaceFile(e, groupId) {
  const f = e.target.files[0];
  if (f) uploadToGroup(groupId, f);
}

async function uploadToGroup(groupId, file) {
  toast(`A processar ${file.name}…`, 'info');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch(`/api/groups/${groupId}/upload`, { method: 'POST', body: fd });
    const d = await r.json();
    if (d.error) { toast(d.error, 'error'); return; }
    toast(
      `${d.bank_name || 'Extrato'} adicionado` +
      (d.movement_count ? ` (${d.movement_count} movimentos)` : ''),
      'success'
    );
    await loadGroups();
    renderGroupsList();
    await loadGroupWorkspace(groupId);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function removeExtract(groupId, extractId) {
  try {
    await fetch(`/api/groups/${groupId}/extracts/${extractId}`, { method: 'DELETE' });
    await loadGroups();
    renderGroupsList();
    await loadGroupWorkspace(groupId);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function confirmDeleteGroup(groupId) {
  if (!confirm('Eliminar este grupo e todos os seus extratos? Esta acção não pode ser desfeita.')) return;
  try {
    await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
    activeGroupId = null;
    await renderConsolidar();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function generateGroup(groupId) {
  toast('A gerar Excel consolidado…', 'info');
  try {
    const r = await fetch(`/api/groups/${groupId}/generate`);
    if (!r.ok) {
      const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      toast(d.error || 'Erro ao gerar Excel', 'error');
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename[^;=\n]*=["']?([^"';\n]+)/);
    const filename = match ? match[1] : 'consolidado.xlsx';
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), { href: url, download: filename }).click();
    URL.revokeObjectURL(url);
    toast('Excel consolidado descarregado!', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}
```

- [ ] **Step 2: Verify the UI renders correctly in the browser**

Reload `http://localhost:5000`. Confirm:
- Converter tab shows drop zone + bank chips
- Clicking "Consolidar" tab shows the groups panel + empty workspace
- Theme toggle switches dark/light and persists across reload

- [ ] **Step 3: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "feat: new app.js — stateless converter + consolidar tab with groups"
```

---

## Task 8: End-to-end smoke test

**Files:** None (verification only)

With the server running (`python backend/app.py`):

- [ ] **Step 1: Test the converter endpoint returns a file**

```bash
curl -s -o /tmp/out.xlsx -D - -F "file=@<path-to-any-bank-pdf>" http://localhost:5000/convert
```

Expected: HTTP 200, `Content-Disposition: attachment; filename="extrato_*.xlsx"`, `X-Bank-Name` header present, `/tmp/out.xlsx` is a valid Excel file.

- [ ] **Step 2: Test an unsupported format returns a JSON error**

```bash
curl -s -F "file=@backend/app.py" http://localhost:5000/convert
```

Expected: `{"error": "Formato não suportado: .py"}` with HTTP 400.

- [ ] **Step 3: Test groups CRUD**

```bash
# Create
curl -s -X POST http://localhost:5000/api/groups \
  -H "Content-Type: application/json" -d '{"name": "Millennium 2025"}'
# → {"id": 1, "name": "Millennium 2025"}

# List
curl -s http://localhost:5000/api/groups
# → {"data": [{"id": 1, "name": "Millennium 2025", "extract_count": 0, ...}]}

# Delete
curl -s -X DELETE http://localhost:5000/api/groups/1
# → {"ok": true}

# Confirm empty
curl -s http://localhost:5000/api/groups
# → {"data": []}
```

- [ ] **Step 4: Test upload to a group**

```bash
# Create group
curl -s -X POST http://localhost:5000/api/groups \
  -H "Content-Type: application/json" -d '{"name": "Test Group"}'
# note the returned id (e.g. 2)

# Upload a bank PDF into it
curl -s -F "file=@<path-to-bank-pdf>" http://localhost:5000/api/groups/2/upload
# → {"extract_id": 1, "bank_name": "...", "movement_count": ..., ...}

# List extracts
curl -s http://localhost:5000/api/groups/2/extracts
# → {"data": [{"id": 1, "bank_name": "...", ...}]}

# Generate consolidated Excel
curl -s -o /tmp/consolidated.xlsx http://localhost:5000/api/groups/2/generate
# → /tmp/consolidated.xlsx is a valid Excel file
```

- [ ] **Step 5: Manual browser flow — Converter tab**

1. Open `http://localhost:5000`
2. Drag a bank PDF onto the drop zone
3. Confirm the progress state appears briefly
4. Confirm the success card shows bank name, movement count, period
5. Confirm the Excel downloads automatically
6. Click "Converter outro ficheiro" — confirms the drop zone resets

- [ ] **Step 6: Manual browser flow — Consolidar tab**

1. Click the "Consolidar" tab
2. Click "+ Novo" and create a group named "BPI 2025"
3. Drag a bank PDF into the workspace drop zone — confirm the extract appears in the table
4. Drag a second PDF — confirm a second row appears
5. Click "⬇ Gerar Excel Consolidado" — confirm download
6. Click the 🗑 icon on an extract — confirm it disappears
7. Click the 🗑 header icon on the group, confirm, group disappears from list

- [ ] **Step 7: Final commit**

If any bugs were fixed during smoke testing, commit them. Otherwise:

```bash
git add -A
git commit -m "chore: smoke test pass — stateless extractor + consolidar UI complete"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|------------|
| Stateless converter: file in → Excel out | Task 4 `/convert`, Task 7 `uploadConverter` |
| TOConline template format output | `fill_template` call in Task 4 (kept untouched) |
| No bank hint, no year input | Removed from upload form; year derived from parsed period |
| Dark/light theme toggle | Task 6 CSS tokens, Task 7 `toggleTheme` |
| Two tabs: Converter / Consolidar | Task 5 HTML, Task 7 `switchTab` |
| Consolidar: named groups | Task 3 `groups` table, Task 4 group routes, Task 7 group UI |
| Consolidar: upload PDFs into a group | Task 4 `/upload` route, Task 7 `uploadToGroup` |
| Consolidar: extract list with period info | Task 4 `/extracts` route, Task 7 `renderExtractsTable` |
| Consolidar: generate merged Excel | Task 4 `/generate` + `_build_consolidated_excel`, Task 7 `generateGroup` |
| Delete a group + cascading cleanup | Task 3 `ON DELETE CASCADE`, Task 4 delete route |
| Delete removed modules | Task 1 |
| Error shown inline (not silent) | Task 7 `showConverterError`, `toast('...', 'error')` |
