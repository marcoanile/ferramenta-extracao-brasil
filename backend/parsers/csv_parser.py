"""CSV bank statement parser with automatic delimiter and encoding detection."""
import io
import logging
from pathlib import Path

import chardet
import pandas as pd

from .detector import detect_parser
from .banks.base import ParsedStatement, Movement, BankParser

log = logging.getLogger(__name__)
helper = BankParser()

DELIMITERS = [";", ",", "\t", "|"]


def parse_csv(file_path: str | Path, bank_hint: str = None) -> ParsedStatement:
    path = Path(file_path)
    raw = path.read_bytes()

    # Detect encoding
    detected = chardet.detect(raw)
    encoding = detected.get("encoding") or "utf-8"
    try:
        text = raw.decode(encoding)
    except Exception:
        text = raw.decode("latin-1", errors="replace")

    # Detect delimiter
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
        # Guess column positions from first data row with a date
        for i, row in df.iterrows():
            cells = [str(c).strip() for c in row]
            date = parser.parse_date(cells[0]) if cells else None
            if date:
                date_col = 0
                desc_col = 1 if len(cells) > 1 else None
                amount_col = 2 if len(cells) > 2 else None
                balance_col = len(cells) - 1 if len(cells) > 3 else None
                break

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
            amount = c - d
        else:
            continue

        balance = None
        if balance_col is not None and balance_col < len(cells):
            balance = helper.clean_amount(str(cells[balance_col]))

        stmt.movements.append(Movement(
            date=date, description=desc, amount=amount,
            balance=balance, movement_type="debit" if amount < 0 else "credit"
        ))
