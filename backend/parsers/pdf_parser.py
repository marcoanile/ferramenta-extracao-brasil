"""PDF bank statement parser using pdfplumber + Tesseract OCR fallback."""
import logging
from pathlib import Path

import pdfplumber

from .detector import detect_parser
from .banks.base import ParsedStatement

log = logging.getLogger(__name__)

# Minimum number of alphanumeric characters required to consider
# pdfplumber's text extraction as meaningful (not a scanned image PDF).
_MIN_TEXT_CHARS = 80


def _is_meaningful(text: str) -> bool:
    return sum(c.isalnum() for c in text) >= _MIN_TEXT_CHARS


def parse_pdf(file_path: str | Path, bank_hint: str = None) -> ParsedStatement:
    path = Path(file_path)
    full_text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text(x_tolerance=2, y_tolerance=2) or "") + "\n"

    filename = path.name.lower()
    if bank_hint:
        filename = bank_hint.lower() + " " + filename

    if _is_meaningful(full_text):
        parser = detect_parser(full_text, filename)
        log.info("PDF %s -> parser: %s (text)", path.name, parser.bank_name)
        if hasattr(parser, "parse_pdf"):
            stmt = parser.parse_pdf(path, filename)
        else:
            stmt = parser.parse(full_text, filename)
        if stmt.movements:
            return stmt
        stmt = _try_table_extraction(path, parser, stmt)
        if stmt.movements:
            return stmt

    # Text layer insufficient — attempt OCR
    log.info("PDF %s has no usable text layer; attempting OCR", path.name)
    ocr_text = _ocr_pdf(path)
    if not _is_meaningful(ocr_text):
        raise ValueError(
            "Não foi possível extrair texto deste PDF. "
            "Verifique se o Tesseract OCR está instalado (winget install UB-Mannheim.TesseractOCR)."
        )

    parser = detect_parser(ocr_text, filename)
    log.info("PDF %s -> parser: %s (OCR)", path.name, parser.bank_name)
    return parser.parse(ocr_text, filename)


def _ocr_pdf(path: Path) -> str:
    """Render each page at 300 DPI via PyMuPDF and OCR with Tesseract (por+eng)."""
    try:
        import fitz  # PyMuPDF — bundles its own renderer, no Poppler needed
        import pytesseract
        from PIL import Image
        import io
    except ImportError as exc:
        raise RuntimeError(
            "Dependências de OCR em falta. Execute: pip install pymupdf pytesseract"
        ) from exc

    text = ""
    doc = fitz.open(str(path))
    for i, page in enumerate(doc):
        # 300 DPI ≈ zoom factor 300/72
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        page_text = pytesseract.image_to_string(img, lang="por+eng")
        log.debug("OCR page %d: %d chars", i + 1, len(page_text))
        text += page_text + "\n"
    doc.close()
    return text


def _try_table_extraction(path: Path, parser, stmt: ParsedStatement) -> ParsedStatement:
    """Attempt pdfplumber table extraction when text extraction yields nothing."""
    from .banks.base import Movement
    log.info("Falling back to table extraction for %s", path.name)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    date = parser.parse_date(str(row[0] or ""))
                    if not date:
                        continue
                    desc = str(row[1] or "").strip()
                    amounts = [parser.clean_amount(str(cell or "")) for cell in row[2:]]
                    if amounts:
                        amount = amounts[0] if len(amounts) == 1 else (amounts[0] - amounts[1] if amounts[1] else amounts[0])
                        balance = amounts[-1] if len(amounts) > 1 else None
                        stmt.movements.append(Movement(
                            date=date, description=desc, amount=amount, balance=balance,
                            movement_type="debit" if amount < 0 else "credit",
                        ))
    return stmt
