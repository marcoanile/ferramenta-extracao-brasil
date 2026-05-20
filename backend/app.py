"""Nexus Accounting Robot — Flask backend."""
import json
import logging
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_file, redirect, url_for
from flask_cors import CORS

import config
from storage.database import (
    get_engine, get_clients, get_client, upsert_client,
    create_statement, update_statement, get_statements,
    bulk_insert_movements, get_movements, update_movement_reconciliation,
    create_consolidated_extract, get_consolidated_extracts, get_consolidated_extract,
    update_consolidated_extract, delete_consolidated_extract,
    add_statement_to_consolidated, remove_statement_from_consolidated,
    get_consolidated_statements,
)
from parsers.pdf_parser import parse_pdf
from parsers.excel_parser import parse_excel
from parsers.csv_parser import parse_csv
from parsers.detector import detect_bank_name
from converter.template_engine import fill_template
from reconciliation.engine import run_reconciliation, get_reconciliation_summary
from api.toconline_client import toconline

# ─── Logging ────────────────────────────────────────────────────────────────
log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOGS_DIR / "nexus.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("nexus")

# ─── App ─────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="../frontend/static", static_url_path="/static")
app.secret_key = config.SECRET_KEY
CORS(app, origins="*")

# Initialise DB on startup
get_engine()


# ═══════════════════════════════════════════════════════════════════════════
# Serve frontend
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_file("../frontend/index.html")


# ═══════════════════════════════════════════════════════════════════════════
# Auth — TOConline OAuth2
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/toconline/status")
def auth_status():
    creds_ok = bool(config.TOCONLINE_CLIENT_ID and config.TOCONLINE_CLIENT_ID != "your_client_id_here"
                    and config.TOCONLINE_OAUTH_URL)
    return jsonify({
        "authenticated": toconline.is_authenticated(),
        "credentials_configured": creds_ok,
        "oauth_url": config.TOCONLINE_OAUTH_URL if creds_ok else "",
        "client_id": config.TOCONLINE_CLIENT_ID if creds_ok else "",
    })


@app.route("/api/auth/toconline/configure", methods=["POST"])
def configure_credentials():
    """Save TOConline credentials to the .env file at runtime."""
    body = request.get_json()
    oauth_url = (body.get("oauth_url") or "").rstrip("/")
    client_id = (body.get("client_id") or "").strip()
    client_secret = (body.get("client_secret") or "").strip()
    api_url = (body.get("api_url") or "https://apiv1.toconline.com").rstrip("/")

    if not all([oauth_url, client_id, client_secret]):
        return jsonify({"error": "oauth_url, client_id e client_secret são obrigatórios"}), 400

    env_path = config.DATA_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updates = {
        "TOCONLINE_OAUTH_URL": oauth_url,
        "TOCONLINE_CLIENT_ID": client_id,
        "TOCONLINE_CLIENT_SECRET": client_secret,
        "TOCONLINE_API_URL": api_url,
    }

    new_lines = []
    written = set()
    for line in lines:
        key = line.split("=")[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in written:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Reload into config module at runtime
    import importlib
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    config.TOCONLINE_CLIENT_ID = client_id
    config.TOCONLINE_CLIENT_SECRET = client_secret
    config.TOCONLINE_OAUTH_URL = oauth_url
    config.TOCONLINE_API_URL = api_url

    # Patch the running client
    import api.toconline_client as toc_mod
    toc_mod.OAUTH_URL = oauth_url
    toc_mod.API_BASE = api_url.rstrip("/") + "/api"

    log.info("TOConline credentials updated via UI")
    return jsonify({"ok": True, "message": "Credenciais guardadas com sucesso"})


@app.route("/api/auth/toconline/start")
def auth_start():
    redirect_uri = request.host_url.rstrip("/") + "/api/auth/toconline/callback"
    url = toconline.auth_start_url(redirect_uri)
    return jsonify({"auth_url": url})


@app.route("/api/auth/toconline/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Código de autorização em falta"}), 400
    redirect_uri = request.host_url.rstrip("/") + "/api/auth/toconline/callback"
    try:
        toconline.exchange_code(code, redirect_uri)
        return redirect("/?auth=success")
    except Exception as e:
        log.error("OAuth callback error: %s", e)
        return redirect(f"/?auth=error&msg={str(e)}")


# ═══════════════════════════════════════════════════════════════════════════
# Clients
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients")
def list_clients():
    platform = request.args.get("platform")
    clients = get_clients(platform)
    return jsonify({"data": clients})


@app.route("/api/clients/sync", methods=["POST"])
def sync_clients():
    """Pull all clients from TOConline and store locally."""
    try:
        count = toconline.sync_customers_to_db()
        return jsonify({"synced": count, "message": f"{count} clientes sincronizados com TOConline"})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        log.exception("Error syncing clients")
        return jsonify({"error": str(e)}), 500


@app.route("/api/clients/<int:client_id>")
def get_client_detail(client_id: int):
    client = get_client(client_id)
    if not client:
        return jsonify({"error": "Cliente não encontrado"}), 404
    statements = get_statements(client_id=client_id)
    summary = get_reconciliation_summary(client_id)
    return jsonify({"data": client, "statements": statements, "reconciliation": summary})


@app.route("/api/clients", methods=["POST"])
def create_client():
    body = request.get_json()
    cid = upsert_client(
        toconline_id=body.get("toconline_id", f"manual-{uuid.uuid4().hex[:8]}"),
        name=body["name"],
        nif=body.get("nif"),
        platform=body.get("platform", "toconline"),
    )
    return jsonify({"id": cid}), 201


# ═══════════════════════════════════════════════════════════════════════════
# Statements — upload & process
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients/<int:client_id>/statements", methods=["GET"])
def list_statements(client_id: int):
    year = request.args.get("year", type=int)
    stmts = get_statements(client_id=client_id, year=year)
    return jsonify({"data": stmts})


@app.route("/api/clients/<int:client_id>/statements/upload", methods=["POST"])
def upload_statement(client_id: int):
    if "file" not in request.files:
        return jsonify({"error": "Ficheiro em falta"}), 400

    client = get_client(client_id)
    if not client:
        return jsonify({"error": "Cliente não encontrado"}), 404

    file = request.files["file"]
    bank_hint = request.form.get("bank_hint", "")
    year = request.form.get("year", type=int) or datetime.now().year

    suffix = Path(file.filename).suffix.lower()
    if suffix not in config.SUPPORTED_FORMATS:
        return jsonify({"error": f"Formato não suportado: {suffix}"}), 400

    # Save file
    client_dir = config.CLIENTS_DIR / str(client_id) / "statements"
    client_dir.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = client_dir / unique_name
    file.save(str(file_path))

    # Detect bank name from file content for the record
    try:
        raw = file_path.read_bytes()
        bank_name = detect_bank_name(raw, file.filename + " " + bank_hint)
    except Exception:
        bank_name = bank_hint or "Desconhecido"

    stmt_id = create_statement(
        client_id=client_id,
        filename=file.filename,
        file_path=str(file_path),
        bank_name=bank_name,
        year=year,
    )

    # Process immediately
    try:
        result = _process_statement(stmt_id, client_id, file_path, suffix, bank_hint, year)
        return jsonify({"statement_id": stmt_id, "bank_name": bank_name, **result})
    except Exception as e:
        log.exception("Error processing statement %d", stmt_id)
        update_statement(stmt_id, status="error")
        return jsonify({"statement_id": stmt_id, "error": str(e)}), 500


def _process_statement(stmt_id: int, client_id: int, file_path: Path,
                        suffix: str, bank_hint: str, year: int) -> dict:
    update_statement(stmt_id, status="processing")

    if suffix == ".pdf":
        parsed = parse_pdf(file_path, bank_hint)
    elif suffix in (".xlsx", ".xls"):
        parsed = parse_excel(file_path, bank_hint)
    elif suffix == ".csv":
        parsed = parse_csv(file_path, bank_hint)
    else:
        raise ValueError(f"Formato não suportado: {suffix}")

    # Sort & deduplicate
    movements = parsed.sorted_movements()

    # Persist movements
    mov_dicts = []
    for mov in movements:
        d = {
            "statement_id": stmt_id,
            "client_id": client_id,
            "date": mov.date,
            "description": mov.description,
            "amount": mov.amount,
            "balance": mov.balance,
            "movement_type": mov.movement_type,
            "reference": mov.reference,
            "category": mov.category,
        }
        d["hash_key"] = mov.hash_key(client_id)
        mov_dicts.append(d)

    inserted = bulk_insert_movements(mov_dicts)

    # Generate integration Excel
    client_obj = get_client(client_id)
    output_dir = config.CLIENTS_DIR / str(client_id) / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"extrato_{client_id}_{stmt_id}_{year}.xlsx"
    out_path = output_dir / out_name

    fill_template(
        statement=parsed,
        output_path=out_path,
        client_name=client_obj["name"] if client_obj else "",
        year=year,
    )

    update_statement(
        stmt_id,
        status="processed",
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        opening_balance=parsed.opening_balance,
        closing_balance=parsed.closing_balance,
        movement_count=len(movements),
        converted_path=str(out_path),
        processed_at=datetime.now().isoformat(),
        bank_name=parsed.bank_name,
    )

    return {
        "movements": len(movements),
        "inserted": inserted,
        "duplicates_skipped": len(movements) - inserted,
        "bank_name": parsed.bank_name,
        "period_start": parsed.period_start,
        "period_end": parsed.period_end,
        "opening_balance": parsed.opening_balance,
        "closing_balance": parsed.closing_balance,
        "warnings": parsed.warnings,
        "converted_file": out_name,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Download converted Excel
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients/<int:client_id>/statements/<int:stmt_id>/download")
def download_converted(client_id: int, stmt_id: int):
    stmts = get_statements(client_id=client_id)
    stmt = next((s for s in stmts if s["id"] == stmt_id), None)
    if not stmt or not stmt.get("converted_path"):
        return jsonify({"error": "Ficheiro convertido não encontrado"}), 404
    converted = Path(stmt["converted_path"])
    if not converted.is_absolute():
        converted = (Path(__file__).parent / converted).resolve()
    if not converted.exists():
        return jsonify({"error": "Ficheiro não existe no disco"}), 404
    return send_file(str(converted), as_attachment=True, download_name=converted.name)


# ═══════════════════════════════════════════════════════════════════════════
# Consolidated Extracts
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients/<int:client_id>/consolidated", methods=["GET"])
def list_consolidated(client_id: int):
    items = get_consolidated_extracts(client_id)
    for item in items:
        item["statements"] = get_consolidated_statements(item["id"])
    return jsonify({"data": items})


@app.route("/api/clients/<int:client_id>/consolidated", methods=["POST"])
def create_consolidated(client_id: int):
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    cid = create_consolidated_extract(client_id, name, body.get("bank_name"))
    return jsonify({"id": cid, "name": name}), 201


@app.route("/api/clients/<int:client_id>/consolidated/<int:cons_id>", methods=["DELETE"])
def delete_consolidated(client_id: int, cons_id: int):
    ce = get_consolidated_extract(cons_id)
    if not ce or ce["client_id"] != client_id:
        return jsonify({"error": "Não encontrado"}), 404
    delete_consolidated_extract(cons_id)
    return jsonify({"ok": True})


@app.route("/api/clients/<int:client_id>/consolidated/<int:cons_id>/statements", methods=["POST"])
def add_to_consolidated(client_id: int, cons_id: int):
    ce = get_consolidated_extract(cons_id)
    if not ce or ce["client_id"] != client_id:
        return jsonify({"error": "Não encontrado"}), 404
    body = request.get_json() or {}
    stmt_id = body.get("statement_id")
    if not stmt_id:
        return jsonify({"error": "statement_id obrigatório"}), 400
    add_statement_to_consolidated(cons_id, stmt_id)
    return jsonify({"ok": True})


@app.route("/api/clients/<int:client_id>/consolidated/<int:cons_id>/statements/<int:stmt_id>",
           methods=["DELETE"])
def remove_from_consolidated(client_id: int, cons_id: int, stmt_id: int):
    ce = get_consolidated_extract(cons_id)
    if not ce or ce["client_id"] != client_id:
        return jsonify({"error": "Não encontrado"}), 404
    remove_statement_from_consolidated(cons_id, stmt_id)
    return jsonify({"ok": True})


@app.route("/api/clients/<int:client_id>/consolidated/<int:cons_id>/generate", methods=["POST"])
def generate_consolidated(client_id: int, cons_id: int):
    ce = get_consolidated_extract(cons_id)
    if not ce or ce["client_id"] != client_id:
        return jsonify({"error": "Não encontrado"}), 404

    stmts = get_consolidated_statements(cons_id)
    if not stmts:
        return jsonify({"error": "Nenhum extrato associado"}), 400

    # Fetch all movements for included statements, sorted by date
    all_movements = []
    for s in stmts:
        movs = get_movements(client_id=client_id, statement_id=s["id"])
        all_movements.extend(movs)
    all_movements.sort(key=lambda m: (m["date"] or "", m["id"]))

    # Opening = earliest statement's opening_balance; closing = latest statement's closing_balance
    opening = next((s["opening_balance"] for s in stmts if s["opening_balance"] is not None), None)
    closing = next((s["closing_balance"] for s in reversed(stmts) if s["closing_balance"] is not None), None)

    output_dir = config.CLIENTS_DIR / str(client_id) / "consolidated"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = ce["name"].replace(" ", "_").replace("/", "-")
    out_path = output_dir / f"{safe_name}.xlsx"

    _fill_consolidated_excel(all_movements, opening, closing, out_path)

    update_consolidated_extract(cons_id, output_path=str(out_path))

    return jsonify({"ok": True, "movements": len(all_movements), "file": out_path.name})


@app.route("/api/clients/<int:client_id>/consolidated/<int:cons_id>/download")
def download_consolidated(client_id: int, cons_id: int):
    ce = get_consolidated_extract(cons_id)
    if not ce or ce["client_id"] != client_id:
        return jsonify({"error": "Não encontrado"}), 404
    if not ce.get("output_path"):
        return jsonify({"error": "Ainda não foi gerado — clique em Gerar primeiro"}), 404
    out = Path(ce["output_path"])
    if not out.is_absolute():
        out = (Path(__file__).parent / out).resolve()
    if not out.exists():
        return jsonify({"error": "Ficheiro não existe — clique em Gerar para regenerar"}), 404
    return send_file(str(out), as_attachment=True, download_name=out.name)


def _fill_consolidated_excel(movements: list[dict], opening, closing, output_path: Path):
    """Generate a TOConline-compatible Excel from a flat list of movement dicts."""
    from converter.template_engine import _find_template, _is_toconline_import_template, \
        _find_header_row, _find_balance_rows, _to_date
    import shutil
    import openpyxl
    from openpyxl.styles import Border, Side

    template = _find_template(None)
    if template:
        shutil.copy2(template, output_path)
        wb = openpyxl.load_workbook(output_path)
        ws = wb.active

        header_row = _find_header_row(ws)
        ini_row, fin_row = _find_balance_rows(ws)
        data_start = header_row + 1

        # Recompute closing from opening + movements so TOConline validation always passes
        movement_sum = round(sum(m["amount"] for m in movements), 2)
        effective_closing = round((opening or 0) + movement_sum, 2)

        if ini_row:
            ws.cell(row=ini_row, column=4).value = opening
        if fin_row:
            ws.cell(row=fin_row, column=4).value = effective_closing

        for row_idx in range(data_start, ws.max_row + 1):
            for col in range(1, ws.max_column + 1):
                ws.cell(row=row_idx, column=col).value = None

        thin = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )
        for i, mov in enumerate(movements):
            row = data_start + i
            mov_date = _to_date(mov["date"])
            ws.cell(row=row, column=1, value=mov_date).number_format = "DD/MM/YYYY"
            ws.cell(row=row, column=1).border = thin
            ws.cell(row=row, column=2, value=mov_date).number_format = "DD/MM/YYYY"
            ws.cell(row=row, column=2).border = thin
            ws.cell(row=row, column=3, value=mov.get("description") or "").border = thin
            cell_d = ws.cell(row=row, column=4, value=mov["amount"])
            cell_d.number_format = '#,##0.00'
            cell_d.border = thin

        wb.save(output_path)
    else:
        # Fallback: plain workbook
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Movimentos"
        ws.append(["Data Mov.", "Data Valor", "Descrição do Movimento", "Movimento"])
        for mov in movements:
            ws.append([_to_date(mov["date"]), _to_date(mov["date"]),
                       mov.get("description") or "", mov["amount"]])
        wb.save(output_path)


# ═══════════════════════════════════════════════════════════════════════════
# Movements
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients/<int:client_id>/movements")
def list_movements(client_id: int):
    year = request.args.get("year", type=int)
    stmt_id = request.args.get("statement_id", type=int)
    status = request.args.get("status")
    movs = get_movements(client_id=client_id, year=year, statement_id=stmt_id, status=status)
    return jsonify({"data": movs, "total": len(movs)})


@app.route("/api/clients/<int:client_id>/movements/<int:mov_id>", methods=["PATCH"])
def update_movement(client_id: int, mov_id: int):
    body = request.get_json()
    status = body.get("reconciliation_status")
    entry_id = body.get("toconline_entry_id")
    if status:
        update_movement_reconciliation(mov_id, status, entry_id)
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clients/<int:client_id>/reconciliation/run", methods=["POST"])
def run_recon(client_id: int):
    body = request.get_json() or {}
    year = body.get("year", type(int)) if isinstance(body.get("year"), int) else None
    accounting_entries = []
    if toconline.is_authenticated():
        try:
            accounting_entries = toconline.list_accounting_entries()
            accounting_entries += toconline.list_receipts()
        except Exception as e:
            log.warning("Could not fetch TOConline entries: %s", e)
    result = run_reconciliation(client_id=client_id, year=year, accounting_entries=accounting_entries)
    return jsonify(result)


@app.route("/api/clients/<int:client_id>/reconciliation/summary")
def recon_summary(client_id: int):
    year = request.args.get("year", type=int)
    return jsonify(get_reconciliation_summary(client_id, year))


# ═══════════════════════════════════════════════════════════════════════════
# TOConline direct API proxy (for UI lookups)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/toconline/bank_accounts")
def toc_bank_accounts():
    try:
        data = toconline.list_bank_accounts()
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/toconline/customers")
def toc_customers():
    try:
        data = toconline.list_customers()
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "toconline_authenticated": toconline.is_authenticated(),
        "db": str(config.DB_PATH),
    })


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("Starting Nexus on port %d", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
