"""SQLite database layer using SQLAlchemy core (no ORM bloat)."""
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, text, Column, Integer, String, Float,
    DateTime, Boolean, Text, MetaData, Table, inspect
)

import config

log = logging.getLogger(__name__)

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        db_url = f"sqlite:///{config.DB_PATH}"
        _engine = create_engine(db_url, connect_args={"check_same_thread": False})
        _init_schema()
    return _engine


def _init_schema():
    engine = _engine
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                toconline_id TEXT UNIQUE,
                name TEXT NOT NULL,
                nif TEXT,
                platform TEXT DEFAULT 'toconline',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                meta TEXT DEFAULT '{}'
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bank_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                bank_name TEXT,
                iban TEXT,
                account_number TEXT,
                account_type TEXT DEFAULT 'checking',
                toconline_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                bank_account_id INTEGER,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                bank_name TEXT,
                year INTEGER,
                period_start TEXT,
                period_end TEXT,
                opening_balance REAL,
                closing_balance REAL,
                movement_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                converted_path TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY(client_id) REFERENCES clients(id),
                FOREIGN KEY(bank_account_id) REFERENCES bank_accounts(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                amount REAL NOT NULL,
                balance REAL,
                movement_type TEXT,
                reference TEXT,
                category TEXT,
                hash_key TEXT UNIQUE,
                reconciliation_status TEXT DEFAULT 'unmatched',
                toconline_entry_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(statement_id) REFERENCES statements(id),
                FOREIGN KEY(client_id) REFERENCES clients(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                movement_id INTEGER NOT NULL,
                toconline_entry_id TEXT,
                match_type TEXT,
                confidence REAL DEFAULT 0.0,
                matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                matched_by TEXT DEFAULT 'auto',
                notes TEXT,
                FOREIGN KEY(client_id) REFERENCES clients(id),
                FOREIGN KEY(movement_id) REFERENCES movements(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                client_id_key TEXT,
                access_token TEXT,
                refresh_token TEXT,
                expires_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS consolidated_extracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                bank_name TEXT,
                output_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS consolidated_extract_statements (
                consolidated_id INTEGER NOT NULL,
                statement_id INTEGER NOT NULL,
                PRIMARY KEY(consolidated_id, statement_id),
                FOREIGN KEY(consolidated_id) REFERENCES consolidated_extracts(id),
                FOREIGN KEY(statement_id) REFERENCES statements(id)
            )
        """))
        conn.commit()
    log.info("Database schema initialised at %s", config.DB_PATH)


# --- Client helpers ---

def upsert_client(toconline_id: str, name: str, nif: str = None, platform: str = "toconline", meta: dict = None) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM clients WHERE toconline_id = :tid"),
            {"tid": toconline_id}
        ).fetchone()
        if row:
            conn.execute(text(
                "UPDATE clients SET name=:name, nif=:nif, updated_at=CURRENT_TIMESTAMP, meta=:meta WHERE toconline_id=:tid"
            ), {"name": name, "nif": nif, "meta": json.dumps(meta or {}), "tid": toconline_id})
            conn.commit()
            return row[0]
        result = conn.execute(text(
            "INSERT INTO clients (toconline_id, name, nif, platform, meta) VALUES (:tid, :name, :nif, :platform, :meta)"
        ), {"tid": toconline_id, "name": name, "nif": nif, "platform": platform, "meta": json.dumps(meta or {})})
        conn.commit()
        return result.lastrowid


def get_clients(platform: str = None) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        if platform:
            rows = conn.execute(text("SELECT * FROM clients WHERE platform=:p ORDER BY name"), {"p": platform}).fetchall()
        else:
            rows = conn.execute(text("SELECT * FROM clients ORDER BY name")).fetchall()
        return [dict(r._mapping) for r in rows]


def get_client(client_id: int) -> dict | None:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM clients WHERE id=:id"), {"id": client_id}).fetchone()
        return dict(row._mapping) if row else None


# --- Statement helpers ---

def create_statement(client_id: int, filename: str, file_path: str, bank_name: str = None,
                     year: int = None, bank_account_id: int = None) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO statements (client_id, filename, file_path, bank_name, year, bank_account_id)
            VALUES (:cid, :fn, :fp, :bank, :year, :baid)
        """), {"cid": client_id, "fn": filename, "fp": str(file_path),
               "bank": bank_name, "year": year, "baid": bank_account_id})
        conn.commit()
        return result.lastrowid


def update_statement(statement_id: int, **kwargs):
    engine = get_engine()
    allowed = {"period_start", "period_end", "opening_balance", "closing_balance",
                "movement_count", "status", "converted_path", "processed_at", "bank_name"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=:{k}" for k in fields)
    fields["sid"] = statement_id
    with engine.connect() as conn:
        conn.execute(text(f"UPDATE statements SET {set_clause} WHERE id=:sid"), fields)
        conn.commit()


def get_statements(client_id: int = None, year: int = None) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        clauses, params = [], {}
        if client_id:
            clauses.append("client_id=:cid")
            params["cid"] = client_id
        if year:
            clauses.append("year=:year")
            params["year"] = year
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(text(f"SELECT * FROM statements {where} ORDER BY uploaded_at DESC"), params).fetchall()
        return [dict(r._mapping) for r in rows]


# --- Movement helpers ---

def bulk_insert_movements(movements: list[dict]) -> int:
    """Insert movements, skipping duplicates by hash_key. Returns inserted count."""
    engine = get_engine()
    inserted = 0
    with engine.connect() as conn:
        for m in movements:
            try:
                result = conn.execute(text("""
                    INSERT OR IGNORE INTO movements
                    (statement_id, client_id, date, description, amount, balance,
                     movement_type, reference, category, hash_key)
                    VALUES (:sid, :cid, :date, :desc, :amount, :balance,
                            :mtype, :ref, :cat, :hash)
                """), {
                    "sid": m["statement_id"], "cid": m["client_id"],
                    "date": m["date"], "desc": m.get("description"),
                    "amount": m["amount"], "balance": m.get("balance"),
                    "mtype": m.get("movement_type"), "ref": m.get("reference"),
                    "cat": m.get("category"), "hash": m.get("hash_key"),
                })
                inserted += result.rowcount
            except Exception as e:
                log.warning("Skip movement insert: %s", e)
        conn.commit()
    return inserted


def get_movements(client_id: int, statement_id: int = None, year: int = None,
                  status: str = None) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        clauses = ["client_id=:cid"]
        params = {"cid": client_id}
        if statement_id:
            clauses.append("statement_id=:sid")
            params["sid"] = statement_id
        if year:
            clauses.append("strftime('%Y', date)=:year")
            params["year"] = str(year)
        if status:
            clauses.append("reconciliation_status=:status")
            params["status"] = status
        where = "WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            text(f"SELECT * FROM movements {where} ORDER BY date, id"),
            params
        ).fetchall()
        return [dict(r._mapping) for r in rows]


def update_movement_reconciliation(movement_id: int, status: str, entry_id: str = None):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE movements SET reconciliation_status=:status, toconline_entry_id=:eid
            WHERE id=:mid
        """), {"status": status, "eid": entry_id, "mid": movement_id})
        conn.commit()


# --- Consolidated extract helpers ---

def create_consolidated_extract(client_id: int, name: str, bank_name: str = None) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO consolidated_extracts (client_id, name, bank_name)
            VALUES (:cid, :name, :bank)
        """), {"cid": client_id, "name": name, "bank": bank_name})
        conn.commit()
        return result.lastrowid


def get_consolidated_extracts(client_id: int) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ce.*,
                   COUNT(ces.statement_id) AS statement_count
            FROM consolidated_extracts ce
            LEFT JOIN consolidated_extract_statements ces ON ces.consolidated_id = ce.id
            WHERE ce.client_id = :cid
            GROUP BY ce.id
            ORDER BY ce.created_at DESC
        """), {"cid": client_id}).fetchall()
        return [dict(r._mapping) for r in rows]


def get_consolidated_extract(consolidated_id: int) -> dict | None:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM consolidated_extracts WHERE id=:id"), {"id": consolidated_id}
        ).fetchone()
        return dict(row._mapping) if row else None


def update_consolidated_extract(consolidated_id: int, **kwargs):
    engine = get_engine()
    allowed = {"name", "bank_name", "output_path"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=:{k}" for k in fields)
    fields["cid"] = consolidated_id
    with engine.connect() as conn:
        conn.execute(text(f"UPDATE consolidated_extracts SET {set_clause} WHERE id=:cid"), fields)
        conn.commit()


def delete_consolidated_extract(consolidated_id: int):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM consolidated_extract_statements WHERE consolidated_id=:cid"),
                     {"cid": consolidated_id})
        conn.execute(text("DELETE FROM consolidated_extracts WHERE id=:cid"), {"cid": consolidated_id})
        conn.commit()


def add_statement_to_consolidated(consolidated_id: int, statement_id: int):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT OR IGNORE INTO consolidated_extract_statements (consolidated_id, statement_id)
            VALUES (:cid, :sid)
        """), {"cid": consolidated_id, "sid": statement_id})
        conn.commit()


def remove_statement_from_consolidated(consolidated_id: int, statement_id: int):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            DELETE FROM consolidated_extract_statements
            WHERE consolidated_id=:cid AND statement_id=:sid
        """), {"cid": consolidated_id, "sid": statement_id})
        conn.commit()


def get_consolidated_statements(consolidated_id: int) -> list[dict]:
    """Return full statement rows linked to this consolidated extract, ordered by period_start."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.*
            FROM statements s
            JOIN consolidated_extract_statements ces ON ces.statement_id = s.id
            WHERE ces.consolidated_id = :cid
            ORDER BY s.period_start ASC, s.id ASC
        """), {"cid": consolidated_id}).fetchall()
        return [dict(r._mapping) for r in rows]


# --- Token storage ---

def save_token(platform: str, access_token: str, refresh_token: str, expires_at: datetime, client_id_key: str = None):
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM auth_tokens WHERE platform=:p"), {"p": platform}).fetchone()
        if row:
            conn.execute(text("""
                UPDATE auth_tokens SET access_token=:at, refresh_token=:rt, expires_at=:ea,
                updated_at=CURRENT_TIMESTAMP, client_id_key=:cik WHERE platform=:p
            """), {"at": access_token, "rt": refresh_token, "ea": expires_at, "cik": client_id_key, "p": platform})
        else:
            conn.execute(text("""
                INSERT INTO auth_tokens (platform, client_id_key, access_token, refresh_token, expires_at)
                VALUES (:p, :cik, :at, :rt, :ea)
            """), {"p": platform, "cik": client_id_key, "at": access_token, "rt": refresh_token, "ea": expires_at})
        conn.commit()


def load_token(platform: str) -> dict | None:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM auth_tokens WHERE platform=:p"), {"p": platform}).fetchone()
        return dict(row._mapping) if row else None
