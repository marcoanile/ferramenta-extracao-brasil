"""Excel (XLSX/XLS) bank statement parser."""
import logging
from pathlib import Path

import openpyxl
import pandas as pd

from .detector import detect_parser
from .banks.base import ParsedStatement, Movement, BankParser

log = logging.getLogger(__name__)

helper = BankParser()


def parse_excel(file_path: str | Path, bank_hint: str = None) -> ParsedStatement:
    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".xls":
            df = pd.read_excel(path, engine="xlrd", header=None, dtype=str)
        else:
            df = pd.read_excel(path, engine="openpyxl", header=None, dtype=str)
    except Exception as e:
        log.error("Failed to read excel %s: %s", path, e)
        return ParsedStatement(bank_name="Desconhecido", warnings=[str(e)])

    # Convert DataFrame to plain text for bank detection
    full_text = df.fillna("").to_string()
    filename = (bank_hint or "").lower() + " " + path.name.lower()

    parser = detect_parser(full_text, filename)
    log.info("Excel %s -> parser: %s", path.name, parser.bank_name)

    stmt = ParsedStatement(bank_name=parser.bank_name)
    _extract_from_dataframe(df, parser, stmt)
    return stmt


def _extract_from_dataframe(df: pd.DataFrame, parser, stmt: ParsedStatement):
    """Find header row then extract movements row by row."""
    date_col = amount_col = desc_col = balance_col = debit_col = credit_col = None
    header_row = None

    # Find the header row by looking for common Portuguese column names
    date_keywords = {"data", "date", "data mov.", "data de valor"}
    desc_keywords = {"descrição", "descricao", "descritivo", "histórico", "historico", "movimento"}
    amount_keywords = {"montante", "valor", "amount", "importância"}
    debit_keywords = {"débito", "debito", "saída", "saida", "out"}
    credit_keywords = {"crédito", "credito", "entrada", "in"}
    balance_keywords = {"saldo", "balance"}

    for i, row in df.iterrows():
        row_lower = [str(c).lower().strip() for c in row]
        if any(k in row_lower for k in date_keywords):
            header_row = i
            for j, cell in enumerate(row_lower):
                if cell in date_keywords:
                    date_col = j
                elif cell in desc_keywords:
                    desc_col = j
                elif cell in debit_keywords:
                    debit_col = j
                elif cell in credit_keywords:
                    credit_col = j
                elif cell in amount_keywords:
                    amount_col = j
                elif cell in balance_keywords:
                    balance_col = j
            break

    if header_row is None:
        stmt.warnings.append("Cabeçalho de colunas não encontrado. Parser genérico de linhas será usado.")
        _generic_row_parse(df, parser, stmt)
        return

    for i, row in df.iterrows():
        if i <= header_row:
            continue
        cells = list(row)
        date_val = str(cells[date_col]).strip() if date_col is not None and date_col < len(cells) else ""
        date = parser.parse_date(date_val)
        if not date:
            continue

        desc = str(cells[desc_col]).strip() if desc_col is not None and desc_col < len(cells) else ""

        if amount_col is not None and amount_col < len(cells):
            amount = helper.clean_amount(str(cells[amount_col]))
        elif debit_col is not None and credit_col is not None:
            debit = helper.clean_amount(str(cells[debit_col])) if debit_col < len(cells) else 0
            credit = helper.clean_amount(str(cells[credit_col])) if credit_col < len(cells) else 0
            amount = credit - debit
        else:
            continue

        balance = None
        if balance_col is not None and balance_col < len(cells):
            balance = helper.clean_amount(str(cells[balance_col]))

        mov = Movement(
            date=date,
            description=desc,
            amount=amount,
            balance=balance,
            movement_type="debit" if amount < 0 else "credit",
        )
        stmt.movements.append(mov)


def _generic_row_parse(df: pd.DataFrame, parser, stmt: ParsedStatement):
    """Last-resort: scan each row looking for a date in the first columns."""
    for _, row in df.iterrows():
        cells = [str(c).strip() for c in row if str(c).strip() and str(c).strip().lower() != "nan"]
        if len(cells) < 2:
            continue
        date = parser.parse_date(cells[0])
        if not date:
            continue
        desc = cells[1] if len(cells) > 1 else ""
        amounts = []
        for c in cells[2:]:
            v = helper.clean_amount(c)
            if v != 0.0:
                amounts.append(v)
        if not amounts:
            continue
        amount = amounts[0]
        balance = amounts[-1] if len(amounts) > 1 else None
        stmt.movements.append(Movement(date=date, description=desc, amount=amount,
                                       balance=balance, movement_type="debit" if amount < 0 else "credit"))
