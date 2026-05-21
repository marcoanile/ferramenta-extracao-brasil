"""CSV bank statement parser with automatic delimiter and encoding detection."""
import io
import logging
import re
from pathlib import Path

import chardet
import pandas as pd

from .detector import detect_parser
from .banks.base import ParsedStatement, Movement, BankParser

log = logging.getLogger(__name__)
helper = BankParser()

DELIMITERS = [";", ",", "\t", "|"]

# Zero-padded signed number with decimal separator, e.g. "-00000000000000015,80"
_SIGNED_ZERO_PAD_RE = re.compile(r'^[+-]\s*0+\d+[,\.]\d+\s*$')


def parse_csv(file_path: str | Path, bank_hint: str = None) -> ParsedStatement:
    path = Path(file_path)
    raw = path.read_bytes()

    detected = chardet.detect(raw)
    encoding = detected.get("encoding") or "utf-8"
    try:
        text = raw.decode(encoding)
    except Exception:
        text = raw.decode("latin-1", errors="replace")

    delimiter = _detect_delimiter(text)
    filename = (bank_hint or "").lower() + " " + path.name.lower()
    parser = detect_parser(text, filename)
    log.info("CSV %s -> delimiter='%s', parser=%s, encoding=%s", path.name, delimiter, parser.bank_name, encoding)

    stmt = ParsedStatement(bank_name=parser.bank_name)

    try:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, header=None, engine="python")
    except Exception as e:
        stmt.warnings.append(f"Erro ao ler CSV: {e}")
        return stmt

    _extract_from_dataframe(df, parser, stmt)
    return stmt


def _detect_delimiter(text: str) -> str:
    first_lines = "\n".join(text.splitlines()[:10])
    counts = {d: first_lines.count(d) for d in DELIMITERS}
    return max(counts, key=counts.get)


def _extract_from_dataframe(df: pd.DataFrame, parser, stmt: ParsedStatement):
    date_col = desc_col = amount_col = balance_col = debit_col = credit_col = None
    header_row = None
    _debit_pre_signed = False

    date_kw = {"data", "date", "data mov", "data valor"}
    desc_kw = {"descri", "histor", "descrit", "movimento", "designa"}
    debit_kw = {"débito", "debito", "saída", "saida", "debit"}
    credit_kw = {"crédito", "credito", "entrada", "credit"}
    amount_kw = {"montante", "valor", "importância", "amount"}
    balance_kw = {"saldo", "balance"}

    for i, row in df.iterrows():
        row_lower = [str(c).lower().strip() for c in row]
        if any(any(k in cell for k in date_kw) for cell in row_lower):
            header_row = i
            for j, cell in enumerate(row_lower):
                if any(k in cell for k in date_kw) and date_col is None:
                    date_col = j
                elif any(k in cell for k in desc_kw) and desc_col is None:
                    desc_col = j
                elif any(k in cell for k in debit_kw) and debit_col is None:
                    debit_col = j
                elif any(k in cell for k in credit_kw) and credit_col is None:
                    credit_col = j
                elif any(k in cell for k in amount_kw) and amount_col is None:
                    amount_col = j
                elif any(k in cell for k in balance_kw) and balance_col is None:
                    balance_col = j
            break

    if header_row is None:
        header_row = -1
        cols = _guess_columns(df, parser)
        date_col = cols["date"]
        desc_col = cols["desc"]
        debit_col = cols["debit"]
        credit_col = cols["credit"]
        amount_col = cols["amount"]
        balance_col = cols["balance"]
        _debit_pre_signed = cols["pre_signed"]

    for i, row in df.iterrows():
        if i <= header_row:
            continue
        cells = list(row)

        date_val = str(cells[date_col]).strip() if date_col is not None and date_col < len(cells) else ""
        date = parser.parse_date(date_val)
        if not date:
            continue

        desc = str(cells[desc_col]).strip() if desc_col is not None and desc_col < len(cells) else ""
        if str(desc).lower() in ("nan", "none", ""):
            desc = ""

        if amount_col is not None and amount_col < len(cells):
            amount = helper.clean_amount(str(cells[amount_col]))
        elif debit_col is not None and credit_col is not None:
            d = helper.clean_amount(str(cells[debit_col]) if debit_col < len(cells) else "0")
            c = helper.clean_amount(str(cells[credit_col]) if credit_col < len(cells) else "0")
            # Pre-signed: debit already carries negative sign, credit positive → sum.
            # Magnitude: debit is a positive absolute amount → c - d.
            amount = (d + c) if _debit_pre_signed else (c - d)
        elif credit_col is not None and debit_col is None:
            # Single signed-amount column stored in credit_col
            amount = helper.clean_amount(str(cells[credit_col]) if credit_col < len(cells) else "0")
        else:
            continue

        if amount == 0.0:
            continue

        balance = None
        if balance_col is not None and balance_col < len(cells):
            balance = helper.clean_amount(str(cells[balance_col]))

        stmt.movements.append(Movement(
            date=date, description=desc, amount=amount,
            balance=balance, movement_type="debit" if amount < 0 else "credit"
        ))


def _guess_columns(df: pd.DataFrame, parser) -> dict:
    """Infer column positions from data rows when no header row is present.

    Scans the first 10 rows to find:
    - date column (first column whose value parses as a date)
    - desc column (first non-date, non-numeric, non-amount text column after date)
    - signed-amount columns: negative-only → debit, positive-only → credit,
      columns that appear with both signs → single amount column
    - balance column (the last always-positive signed column)

    Returns a dict with keys: date, desc, debit, credit, amount, balance, pre_signed.
    pre_signed=True means debit/credit cols carry their own sign (use d+c, not c-d).
    """
    date_col = desc_col = debit_col = credit_col = amount_col = balance_col = None
    col_has_neg: dict[int, bool] = {}
    col_has_pos: dict[int, bool] = {}

    for i, row in df.head(10).iterrows():
        cells = [str(c).strip() for c in row]

        if date_col is None:
            for j, cell in enumerate(cells):
                if parser.parse_date(cell):
                    date_col = j
                    break
            if date_col is not None:
                for j in range(date_col + 1, len(cells)):
                    cell = cells[j]
                    if (cell
                            and not parser.parse_date(cell)
                            and not re.match(r'^[\d\s]+$', cell)
                            and not _SIGNED_ZERO_PAD_RE.match(cell)):
                        desc_col = j
                        break

        for j, cell in enumerate(cells):
            if _SIGNED_ZERO_PAD_RE.match(cell):
                val = helper.clean_amount(cell)
                if val < 0:
                    col_has_neg[j] = True
                elif val > 0:
                    col_has_pos[j] = True

    if date_col is None:
        return {"date": None, "desc": None, "debit": None, "credit": None,
                "amount": None, "balance": None, "pre_signed": False}

    neg_only = sorted(j for j in col_has_neg if j not in col_has_pos)
    pos_only = sorted(j for j in col_has_pos if j not in col_has_neg)
    mixed = sorted(j for j in col_has_neg if j in col_has_pos)

    pre_signed = False

    if neg_only and pos_only:
        # Separate debit (negative) and credit (positive) columns — pre-signed format.
        debit_col = neg_only[0]
        credit_col = pos_only[0]
        # If there's a second always-positive column after the credit, it's the balance.
        remaining_pos = [j for j in pos_only if j != credit_col]
        balance_col = remaining_pos[0] if remaining_pos else None
        pre_signed = True
    elif mixed:
        # Single column carries both debits and credits (already signed).
        amount_col = mixed[0]
        balance_col = mixed[1] if len(mixed) > 1 else (pos_only[0] if pos_only else None)
    elif pos_only:
        # Only credits seen in sample — treat first as amount, second as balance.
        amount_col = pos_only[0]
        balance_col = pos_only[1] if len(pos_only) > 1 else None
    else:
        # Fallback: amount is 1 column after desc, balance is last column.
        if desc_col is not None:
            amount_col = desc_col + 1 if desc_col + 1 < df.shape[1] else None
        if amount_col is not None and amount_col + 1 < df.shape[1]:
            balance_col = df.shape[1] - 1

    return {
        "date": date_col, "desc": desc_col,
        "debit": debit_col, "credit": credit_col,
        "amount": amount_col, "balance": balance_col,
        "pre_signed": pre_signed,
    }
