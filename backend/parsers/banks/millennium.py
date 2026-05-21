"""Millennium BCP statement parser (PDF and CSV)."""
import re
from pathlib import Path
from .base import BankParser, ParsedStatement, Movement


class MillenniumParser(BankParser):
    bank_name = "Millennium BCP"

    SIGNATURES = ["millennium", "millenniumbcp", "banco comercial portugu", "millenniumbcp.pt"]

    # Column x-coordinate thresholds for Millennium PDF layout
    _DEBIT_X0_MIN = 330
    _DEBIT_X1_MAX = 400
    _CREDIT_X0_MIN = 410
    _CREDIT_X1_MAX = 480
    _SALDO_X0_MIN = 505
    _DESC_X0_MIN = 110
    _DESC_X0_MAX = 330
    _DATE_X0_MAX = 115

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        text_lower = text.lower() + filename.lower()
        return any(s in text_lower for s in self.SIGNATURES)

    def parse_pdf(self, path, filename: str) -> ParsedStatement:
        """Parse Millennium PDF using word positions to correctly split DEBITO/CREDITO columns."""
        import pdfplumber

        stmt = ParsedStatement(bank_name=self.bank_name)

        with pdfplumber.open(Path(path)) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

            self._extract_header(full_text, stmt)
            year = self._extract_year(full_text)

            for page in pdf.pages:
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                self._extract_movements_from_words(words, stmt, year)

        return stmt

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        """Text-based fallback (used when only extracted text is available)."""
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        self._extract_movements_text(text, stmt)
        return stmt

    # ── Header ────────────────────────────────────────────────────────────────

    def _extract_year(self, text: str) -> int | None:
        # "EXTRATO DE 2025/01/01 A ..." or "N. 2026/001" or top-of-page date "26/01/30"
        for pattern in [
            r"EXTRATO\s+DE\s+(\d{4})/",
            r"N\.\s+(\d{4})/",
            r"\b(20\d{2})/\d{2}/\d{2}\b",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return int(m.group(1))
        return None

    def _extract_header(self, text: str, stmt: ParsedStatement):
        iban_m = re.search(r"IBAN[:\s]+([A-Z]{2}\d{2}[\w\s]{10,30})", text, re.IGNORECASE)
        if iban_m:
            stmt.iban = iban_m.group(1).replace(" ", "")

        # "EXTRATO DE 2025/07/01 A 2025/07/31"
        ext_m = re.search(
            r"EXTRATO\s+DE\s+(\d{4}/\d{2}/\d{2})\s+A\s+(\d{4}/\d{2}/\d{2})", text, re.IGNORECASE
        )
        if ext_m:
            stmt.period_start = ext_m.group(1).replace("/", "-")
            stmt.period_end = ext_m.group(2).replace("/", "-")
        else:
            period_m = re.search(r"per[ií]odo[^\d]*([\d/\-\.]+)\s+a\s+([\d/\-\.]+)", text, re.IGNORECASE)
            if period_m:
                stmt.period_start = self.parse_date(period_m.group(1))
                stmt.period_end = self.parse_date(period_m.group(2))

        bal_m = re.search(r"SALDO\s+INICIAL[^\d]*([\d\s]+\.\d{2})", text, re.IGNORECASE)
        if bal_m:
            stmt.opening_balance = self.clean_amount(bal_m.group(1))

        cbal_m = re.search(r"SALDO\s+FINAL[^\d]*([\d\s]+\.\d{2})", text, re.IGNORECASE)
        if cbal_m:
            stmt.closing_balance = self.clean_amount(cbal_m.group(1))

    # ── Word-position extraction ───────────────────────────────────────────────

    def _extract_movements_from_words(self, words, stmt: ParsedStatement, year: int = None):
        for row in self._group_words_by_row(words):
            # Date: M.DD format, leftmost columns (x0 < 115)
            date_words = [
                w for w in row
                if w["x0"] < self._DATE_X0_MAX and re.match(r"^\d{1,2}\.\d{2}$", w["text"])
            ]
            if not date_words:
                continue

            # Description
            desc_words = sorted(
                [w for w in row if self._DESC_X0_MIN <= w["x0"] < self._DESC_X0_MAX],
                key=lambda w: w["x0"],
            )
            if not desc_words:
                continue

            # Debit column (amount ends at x1 ~385)
            debit_words = sorted(
                [w for w in row if w["x0"] >= self._DEBIT_X0_MIN and w["x1"] <= self._DEBIT_X1_MAX],
                key=lambda w: w["x0"],
            )

            # Credit column (amount ends at x1 ~463)
            credit_words = sorted(
                [w for w in row if w["x0"] >= self._CREDIT_X0_MIN and w["x1"] <= self._CREDIT_X1_MAX],
                key=lambda w: w["x0"],
            )

            if not debit_words and not credit_words:
                continue

            # Balance column (x0 >= 505)
            saldo_words = sorted(
                [w for w in row if w["x0"] >= self._SALDO_X0_MIN],
                key=lambda w: w["x0"],
            )

            date = self._parse_millennium_date(date_words[0]["text"], year)
            if not date:
                continue

            if debit_words:
                amount = -abs(self.clean_amount(" ".join(w["text"] for w in debit_words)))
            else:
                amount = abs(self.clean_amount(" ".join(w["text"] for w in credit_words)))

            balance = None
            if saldo_words:
                balance = self.clean_amount(" ".join(w["text"] for w in saldo_words))

            description = " ".join(w["text"] for w in desc_words).strip()

            mov = Movement(
                date=date,
                description=description,
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            )
            stmt.movements.append(mov)

    def _group_words_by_row(self, words, y_tol: int = 2) -> list:
        """Group words into rows by their vertical (top) position."""
        rows: list[list] = []
        for w in sorted(words, key=lambda x: x["top"]):
            placed = False
            for row in rows:
                if abs(row[0]["top"] - w["top"]) <= y_tol:
                    row.append(w)
                    placed = True
                    break
            if not placed:
                rows.append([w])
        return rows

    def _parse_millennium_date(self, date_str: str, year: int = None) -> str | None:
        """Convert Millennium M.DD date string to YYYY-MM-DD."""
        m = re.match(r"^(\d{1,2})\.(\d{2})$", date_str)
        if not m:
            return None
        month, day = int(m.group(1)), int(m.group(2))
        if year is None:
            from datetime import date
            year = date.today().year
        try:
            return f"{year}-{month:02d}-{day:02d}"
        except Exception:
            return None

    # ── Text-based fallback ────────────────────────────────────────────────────

    def _extract_movements_text(self, text: str, stmt: ParsedStatement):
        pattern = re.compile(
            r"(\d{2}[/\-]\d{2}[/\-]\d{4})\s+"
            r"(.+?)\s+"
            r"([\d.,]+)\s*([DC])\s+"
            r"([\d.,]+)",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            date_str, desc, amount_str, dc, balance_str = m.groups()
            amount = self.clean_amount(amount_str)
            if dc.upper() == "D":
                amount = -abs(amount)
            mov = Movement(
                date=self.parse_date(date_str),
                description=desc.strip(),
                amount=amount,
                balance=self.clean_amount(balance_str),
                movement_type="debit" if amount < 0 else "credit",
            )
            if mov.date:
                stmt.movements.append(mov)
