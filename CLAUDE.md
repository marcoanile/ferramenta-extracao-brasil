# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (Windows)
install.bat
# Or manually:
python -m venv venv && venv\Scripts\activate && pip install -r backend\requirements.txt

# Run
run.bat
# Or manually:
venv\Scripts\activate && cd backend && python app.py
# → http://localhost:5000

# Debug mode (auto-reload on file changes)
# Set DEBUG=true in .env then restart
```

No test suite is currently configured.

## Architecture

Full-stack Flask + SQLite + Vanilla JS single-page app. The UI lives in `frontend/` and talks exclusively to the Flask backend via REST. The backend is in `backend/`.

### Core Data Flow

1. User uploads a bank statement (PDF/Excel/CSV) for a client
2. `parsers/detector.py` auto-detects the bank format using `can_parse()` on each bank parser
3. The matched parser extracts movements and normalises them into `ParsedStatement` (see `parsers/banks/base.py`)
4. Movements are hash-deduplicated and stored in SQLite via `storage/database.py`
5. `converter/template_engine.py` fills a TOConline-compatible Excel template for import
6. Optionally, `reconciliation/engine.py` fuzzy-matches movements to TOConline accounting entries using rapidfuzz

### Key Files

| File | Role |
|------|------|
| `backend/app.py` | All Flask routes and request handlers |
| `backend/config.py` | Loads `.env`, defines all paths and settings |
| `backend/storage/database.py` | SQLite schema (SQLAlchemy) and all query functions |
| `backend/parsers/detector.py` | Tries each bank parser; falls back to `generic.py` |
| `backend/parsers/banks/*.py` | One file per supported bank format |
| `backend/reconciliation/engine.py` | Orchestrates matching and persists results |
| `backend/reconciliation/matcher.py` | Fuzzy-match logic (rapidfuzz) |
| `backend/converter/template_engine.py` | Generates the Excel file for TOConline import |
| `backend/api/toconline_client.py` | OAuth2 flow + TOConline REST API wrapper |
| `frontend/static/js/app.js` | Entire frontend: views, state, API calls |

### Adding a New Bank Parser

1. Create `backend/parsers/banks/<bankname>.py` implementing `can_parse(content, filename) -> bool` and `parse(...) -> ParsedStatement`
2. Register it in `backend/parsers/detector.py` parser list

### Configuration (`.env`)

```
TOCONLINE_CLIENT_ID=
TOCONLINE_CLIENT_SECRET=
TOCONLINE_OAUTH_URL=       # custom URL per TOConline account
TOCONLINE_API_URL=https://apiv1.toconline.com
SECRET_KEY=                # Flask session key
DATA_DIR=../data           # default: project/data
PORT=5000
DEBUG=false
```

Credentials can also be saved at runtime via the UI (`POST /api/auth/toconline/configure`) — no restart needed.

### Runtime Data Layout

```
data/
├── nexus.db                        # SQLite database
├── clients/<id>/statements/        # Uploaded originals
├── clients/<id>/converted/         # Generated Excel files
├── templates/                      # TOConline Excel templates
└── logs/nexus.log                  # Application log
```

## Tech Stack

- **Backend:** Python 3.11+, Flask 3.0.3, SQLAlchemy 2.0, SQLite
- **Parsing:** pdfplumber (PDF), openpyxl + xlrd (Excel), pandas (CSV)
- **Matching:** rapidfuzz (fuzzy string similarity)
- **Frontend:** Vanilla JS, HTML5, CSS3 (no build step)
- **External API:** TOConline (Portuguese accounting SaaS) via OAuth2

## Supported Banks

Millennium BCP, BPI, Caixa Geral de Depósitos, Santander, Novo Banco, BIC/Eurobic, Crédito Agrícola, plus a generic fallback parser.
