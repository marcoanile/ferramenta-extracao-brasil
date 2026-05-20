"""Reconciliation matching — rule-based first, fuzzy fallback."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from rapidfuzz import fuzz

log = logging.getLogger(__name__)

# Days tolerance for cross-month / value-date differences
DATE_TOLERANCE_DAYS = 5
# Minimum similarity score (0-100) for a fuzzy description match
FUZZY_THRESHOLD = 78
# Amount tolerance for floating-point rounding
AMOUNT_TOLERANCE = 0.02


def match_movements_to_entries(
    movements: list[dict],
    accounting_entries: list[dict],
) -> list[dict]:
    """
    Match bank movements to TOConline accounting entries.

    Returns a list of result dicts with keys:
        movement_id, entry_id (or None), match_type, confidence, notes
    """
    results = []
    used_entry_ids = set()

    for mov in movements:
        result = _try_match(mov, accounting_entries, used_entry_ids)
        results.append(result)
        if result["entry_id"]:
            used_entry_ids.add(result["entry_id"])

    return results


def _try_match(mov: dict, entries: list[dict], used: set) -> dict:
    mov_amount = mov.get("amount", 0)
    mov_date = _parse_date(mov.get("date", ""))
    mov_desc = (mov.get("description") or "").lower().strip()

    candidates = [e for e in entries if e.get("id") not in used]

    # --- Rule 1: exact amount + exact date ---
    for entry in candidates:
        if _amounts_match(mov_amount, _entry_amount(entry)) and _dates_match(mov_date, _entry_date(entry), 0):
            return _result(mov, entry, "exact", 1.0, "Data e valor exactos")

    # --- Rule 2: exact amount + date within tolerance ---
    for entry in candidates:
        if _amounts_match(mov_amount, _entry_amount(entry)) and _dates_match(mov_date, _entry_date(entry), DATE_TOLERANCE_DAYS):
            return _result(mov, entry, "amount_date", 0.92, f"Valor exacto, data ±{DATE_TOLERANCE_DAYS}d")

    # --- Rule 3: exact amount + fuzzy description ---
    for entry in candidates:
        if _amounts_match(mov_amount, _entry_amount(entry)):
            entry_desc = _entry_desc(entry).lower()
            score = fuzz.token_set_ratio(mov_desc, entry_desc)
            if score >= FUZZY_THRESHOLD:
                return _result(mov, entry, "amount_fuzzy_desc", score / 100,
                               f"Valor exacto, descrição similar ({score}%)")

    # --- Rule 4: fuzzy description + date tolerance (partial match) ---
    best_score = 0
    best_entry = None
    for entry in candidates:
        if not _dates_match(mov_date, _entry_date(entry), DATE_TOLERANCE_DAYS * 2):
            continue
        entry_desc = _entry_desc(entry).lower()
        score = fuzz.token_set_ratio(mov_desc, entry_desc)
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry and best_score >= FUZZY_THRESHOLD + 5:
        return _result(mov, best_entry, "fuzzy", best_score / 100,
                       f"Correspondência fuzzy ({best_score}%) — verificar manualmente")

    return {"movement_id": mov["id"], "entry_id": None,
            "match_type": "unmatched", "confidence": 0.0, "notes": "Sem correspondência"}


def _result(mov, entry, match_type, confidence, notes) -> dict:
    return {
        "movement_id": mov["id"],
        "entry_id": entry.get("id"),
        "match_type": match_type,
        "confidence": round(confidence, 4),
        "notes": notes,
    }


def _amounts_match(a: float, b: float) -> bool:
    return abs(abs(a) - abs(b)) <= AMOUNT_TOLERANCE


def _dates_match(d1, d2, tolerance_days: int) -> bool:
    if not d1 or not d2:
        return False
    return abs((d1 - d2).days) <= tolerance_days


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _entry_amount(entry: dict) -> float:
    attrs = entry.get("attributes", entry)
    for key in ("amount", "value", "gross_total", "net_total", "debit_amount", "credit_amount"):
        v = attrs.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return 0.0


def _entry_date(entry: dict):
    attrs = entry.get("attributes", entry)
    for key in ("date", "value_date", "created_at", "updated_at"):
        v = attrs.get(key)
        if v:
            d = _parse_date(str(v))
            if d:
                return d
    return None


def _entry_desc(entry: dict) -> str:
    attrs = entry.get("attributes", entry)
    for key in ("description", "notes", "observations", "internal_observations", "document_no"):
        v = attrs.get(key)
        if v:
            return str(v)
    return ""
