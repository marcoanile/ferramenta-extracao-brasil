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
