# Spec: Stateless Extractor Redesign

**Date:** 2026-05-21
**Status:** Approved

## Problem

The current app is built around a multi-view SaaS-style shell (Dashboard, Clientes, Configurações, Reconciliar, TOConline OAuth) that is far heavier than the actual use case: convert a bank statement PDF/Excel/CSV into a TOConline-compatible Excel file. All that scaffolding creates friction and noise for a tool with one real job.

## Goal

Strip everything except two features:
1. **Converter** — stateless, single-file upload → immediate Excel download
2. **Consolidar** — accumulate monthly extracts into a named group over time, then generate one merged Excel

## Out of Scope

- TOConline OAuth and API integration
- Client management and sync
- Reconciliation engine
- Dashboard stats
- Consolidated extracts linked to clients (replaced by standalone named groups)

---

## UI Design

### Layout

Single HTML page. No sidebar. Minimal header:
- Left: logo + "Nexus Extrator"
- Right: theme toggle (dark/light, persisted in localStorage)

Two tabs below the header: **Converter** | **Consolidar**

### Converter Tab — Three States

**Idle**
- Subtitle: "Arraste um extrato bancário e receba o Excel pronto a importar."
- Large drag-and-drop zone accepting `.pdf`, `.xlsx`, `.xls`, `.csv`
- Below the zone: supported banks listed as small chips (Millennium, BPI, CGD, Santander, Novo Banco, Bankinter, Crédito Agrícola)

**Processing**
- Progress bar (animated, indeterminate)
- Text: "A processar…" → updates to "Banco detectado: [name]" once the response arrives
- Cancel is not needed (conversion is fast)

**Done**
- Success card showing: detected bank · movement count · period (DD/MM/YYYY → DD/MM/YYYY)
- Primary button: "⬇ Descarregar Excel" (triggers browser download)
- Secondary button: "Converter outro ficheiro" (resets to Idle state)
- The tab stays in Done state until the user explicitly resets or navigates away

### Consolidar Tab

**Left panel — group list (fixed width ~220px)**
- "+ Novo Grupo" button at top → inline input to name the group, confirm with Enter
- List of existing groups, each showing name + extract count
- Active group is highlighted

**Right panel — active group workspace**
- Group name as heading
- Two action buttons top-right: "Gerar Excel Consolidado" (primary) · delete group (icon, with confirmation)
- Drag-and-drop upload zone (same style as Converter tab) — dropping a file uploads it into this group
- Table of added extracts:
  - Columns: Banco | Período | Movimentos | (delete icon)
  - Sorted by period start date ascending
  - Empty state: "Ainda sem extratos. Arraste um ficheiro para começar."
- Generating the Excel triggers a download of the merged file; a toast confirms success

**Error handling (both tabs)**
- If parsing fails (unrecognised format, corrupt file): red inline error message with the raw error text from the backend. No silent failures.
- If no template file is found: backend falls back to a plain Excel (same behaviour as today).

---

## Backend Design

### Routes

All existing routes are removed and replaced with:

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/` | Serve `index.html` |
| `POST` | `/convert` | Stateless convert: multipart file → Excel attachment |
| `GET` | `/api/groups` | List all groups `[{id, name, extract_count, created_at}]` |
| `POST` | `/api/groups` | Create group `{name}` → `{id, name}` |
| `DELETE` | `/api/groups/<id>` | Delete group + all its extracts and movements |
| `POST` | `/api/groups/<id>/upload` | Upload file → converts + stores movements → `{extract_id, bank_name, period_start, period_end, movement_count}` |
| `DELETE` | `/api/groups/<id>/extracts/<eid>` | Remove one extract and its movements from the group |
| `GET` | `/api/groups/<id>/generate` | Generate merged Excel → file attachment |

### `/convert` endpoint

1. Receive multipart file
2. Detect suffix → call `parse_pdf` / `parse_excel` / `parse_csv`
3. Call `fill_template(statement, output_path, client_name="", year=period_year)`
4. Return `send_file(..., as_attachment=True)` with filename `extrato_<bank>_<period>.xlsx`
5. Clean up temp file after response

No database writes. No client lookup. Year is derived from the parsed period (fallback: current year).

### `/api/groups/<id>/upload` endpoint

1. Receive multipart file
2. Parse (same pipeline as `/convert`)
3. Write movements to `movements` table with `group_id` + `extract_id`
4. Write one row to `extracts` table
5. Return extract summary JSON

### `/api/groups/<id>/generate` endpoint

1. Load all movements for the group, ordered by `date ASC`
2. Compute opening balance = earliest movement's prior balance (or 0 if unavailable)
3. Call `fill_template` / `_fill_consolidated_excel` with the flat movement list
4. Return `send_file(..., as_attachment=True)`

---

## Database Schema

Used only by the Consolidar feature. Managed by SQLAlchemy / raw SQLite — no ORM overhead needed.

```sql
CREATE TABLE groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE extracts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    filename       TEXT,
    bank_name      TEXT,
    period_start   TEXT,
    period_end     TEXT,
    movement_count INTEGER,
    added_at       TEXT NOT NULL
);

CREATE TABLE movements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    extract_id   INTEGER NOT NULL REFERENCES extracts(id) ON DELETE CASCADE,
    group_id     INTEGER NOT NULL,
    date         TEXT,
    description  TEXT,
    amount       REAL,
    balance      REAL
);
```

`ON DELETE CASCADE` means deleting a group deletes its extracts and movements automatically.

---

## Files

### Deleted

| Path | Reason |
|------|--------|
| `backend/api/` | TOConline + Cegid clients — entire folder removed |
| `backend/reconciliation/` | Reconciliation engine — entire folder removed |
| `backend/storage/file_store.py` | Replaced by new minimal DB module |

### Rewritten

| Path | Notes |
|------|-------|
| `backend/app.py` | ~150 lines, 8 routes only |
| `backend/storage/database.py` | New minimal schema (groups/extracts/movements) |
| `backend/config.py` | Remove TOConline vars; keep DATA_DIR, PORT, DEBUG, SECRET_KEY |
| `frontend/index.html` | New two-tab layout, no sidebar, no auth modal |
| `frontend/static/js/app.js` | New focused JS, ~350 lines |
| `frontend/static/css/style.css` | Keep design tokens, strip unused sidebar/client/modal rules |

### Kept Untouched

| Path | Reason |
|------|--------|
| `backend/parsers/` | All bank parsers + detector — no changes needed |
| `backend/converter/template_engine.py` | Excel generation — no changes needed |

---

## Open Questions

None. All design decisions are resolved.
