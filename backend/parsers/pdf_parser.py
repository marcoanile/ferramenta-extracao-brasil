"""PDF bank statement parser using pdfplumber."""
import logging
from pathlib import Path

import pdfplumber

from .detector import detect_parser
from .banks.base import ParsedStatement

log = logging.getLogger(__name__)


def parse_pdf(file_path: str | Path, bank_hint: str = None) -> ParsedStatement:
    """Extract all text from a PDF (all pages) and run the bank parser."""
    path = Path(file_path)
    full_text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            full_text += page_text + "\n"

    filename = path.name.lower()
    if bank_hint:
        filename = bank_hint.lower() + " " + filename

    parser = detect_parser(full_text, filename)
    log.info("PDF %s -> parser: %s", path.name, parser.bank_name)
    if hasattr(parser, "parse_pdf"):
        stmt = parser.parse_pdf(path, filename)
    else:
        stmt = parser.parse(full_text, filename)

    if not stmt.movements:
        # Try table extraction as fallback
        stmt = _try_table_extraction(path, parser, stmt)

    return stmt


def _try_table_extraction(path: Path, parser, stmt: ParsedStatement) -> ParsedStatement:
    """Attempt pdfplumber table extraction when text extraction yields nothing."""
    from .banks.base import Movement
    log.info("Falling back to table extraction for %s", path.name)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    # Try to find date in first column
                    date = parser.parse_date(str(row[0] or ""))
                    if not date:
                        continue
                    desc = str(row[1] or "").strip()
                    # Find amount columns
                    amounts = []
                    for cell in row[2:]:
                        val = parser.clean_amount(str(cell or ""))
                        amounts.append(val)

                    if amounts:
                        amount = amounts[0] if len(amounts) == 1 else (amounts[0] - amounts[1] if amounts[1] else amounts[0])
                        balance = amounts[-1] if len(amounts) > 1 else None
                        mov = Movement(
                            date=date,
                            description=desc,
                            amount=amount,
                            balance=balance,
                            movement_type="debit" if amount < 0 else "credit",
                        )
                        stmt.movements.append(mov)
    return stmt
