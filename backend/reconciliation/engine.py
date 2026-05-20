"""Reconciliation engine — orchestrates matching and persists results."""
import logging

from storage.database import (
    get_movements, update_movement_reconciliation,
    get_engine
)
from .matcher import match_movements_to_entries
from sqlalchemy import text

log = logging.getLogger(__name__)


def run_reconciliation(client_id: int, year: int = None,
                       accounting_entries: list[dict] = None) -> dict:
    """
    Match all unmatched movements for a client against accounting entries.

    accounting_entries: list of TOConline entry dicts. If None, skips API matching.
    Returns summary dict with counts.
    """
    movements = get_movements(client_id=client_id, year=year, status="unmatched")
    if not movements:
        return {"matched": 0, "unmatched": 0, "total": 0, "message": "Sem movimentos por reconciliar"}

    entries = accounting_entries or []
    results = match_movements_to_entries(movements, entries)

    matched = 0
    for res in results:
        mov_id = res["movement_id"]
        entry_id = res.get("entry_id")
        match_type = res["match_type"]
        confidence = res["confidence"]

        if match_type == "unmatched":
            status = "unmatched"
        elif confidence >= 0.90:
            status = "matched"
            matched += 1
        else:
            status = "review"
            matched += 1  # counts as handled, but flagged for review

        update_movement_reconciliation(mov_id, status, str(entry_id) if entry_id else None)
        _save_reconciliation_record(client_id, mov_id, entry_id, match_type, confidence, res.get("notes", ""))

    total = len(movements)
    unmatched = total - matched
    log.info("Reconciliation: client=%d, total=%d, matched=%d, unmatched=%d", client_id, total, matched, unmatched)
    return {"matched": matched, "unmatched": unmatched, "total": total}


def _save_reconciliation_record(client_id, movement_id, entry_id, match_type, confidence, notes):
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT OR REPLACE INTO reconciliations
            (client_id, movement_id, toconline_entry_id, match_type, confidence, notes)
            VALUES (:cid, :mid, :eid, :mt, :conf, :notes)
        """), {
            "cid": client_id, "mid": movement_id,
            "eid": str(entry_id) if entry_id else None,
            "mt": match_type, "conf": confidence, "notes": notes
        })
        conn.commit()


def get_reconciliation_summary(client_id: int, year: int = None) -> dict:
    all_movs = get_movements(client_id=client_id, year=year)
    matched = [m for m in all_movs if m["reconciliation_status"] == "matched"]
    review = [m for m in all_movs if m["reconciliation_status"] == "review"]
    unmatched = [m for m in all_movs if m["reconciliation_status"] == "unmatched"]
    return {
        "total": len(all_movs),
        "matched": len(matched),
        "review": len(review),
        "unmatched": len(unmatched),
        "matched_pct": round(len(matched) / len(all_movs) * 100, 1) if all_movs else 0,
    }
