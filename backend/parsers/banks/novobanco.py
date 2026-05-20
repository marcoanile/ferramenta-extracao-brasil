"""Novo Banco statement parser (PDF)."""
import re
from pathlib import Path
from .base import BankParser, ParsedStatement, Movement


class NovoBancoParser(BankParser):
    bank_name = "Novo Banco"

    SIGNATURES = ["novo banco", "novobanco", "espirito santo", "bescptpl"]

    _DATE_X0_MAX = 65
    _DESC_X0_MIN = 105

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        text_lower = text.lower() + filename.lower()
        return any(s in text_lower for s in self.SIGNATURES)

    def parse_pdf(self, path, filename: str) -> ParsedStatement:
        import pdfplumber
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._stop_parsing = False
        with pdfplumber.open(Path(path)) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text(x_tolerance=2, y_tolerance=2) or "") + "\n"
            self._extract_header(full_text, stmt)
            for page in pdf.pages:
                if self._stop_parsing:
                    break
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                self._extract_movements_from_words(words, stmt)
        return stmt

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        return stmt

    # ── Header ────────────────────────────────────────────────────────────────

    def _extract_header(self, text: str, stmt: ParsedStatement):
        iban_m = re.search(r"IBAN\s+(PT\d{2}(?:\s*\d{4}){5}\s*\d{1,3})", text, re.IGNORECASE)
        if iban_m:
            stmt.iban = re.sub(r"\s+", "", iban_m.group(1))

        period_m = re.search(
            r"de\s+(\d{2}\.\d{2}\.\d{4})\s+a\s+(\d{2}\.\d{2}\.\d{4})", text, re.IGNORECASE
        )
        if period_m:
            stmt.period_start = self._parse_nb_date_long(period_m.group(1))
            stmt.period_end = self._parse_nb_date_long(period_m.group(2))

        bal_m = re.search(r"SALDO\s+ANTERIOR\s+([\d.,]+)", text, re.IGNORECASE)
        if bal_m:
            stmt.opening_balance = self.clean_amount(bal_m.group(1))

        cbal_m = re.search(r"SALDO\s+CONTAB[^\s]*\s+([\d.,]+)", text, re.IGNORECASE)
        if cbal_m:
            stmt.closing_balance = self.clean_amount(cbal_m.group(1))

    # ── Word-position extraction ───────────────────────────────────────────────

    def _extract_movements_from_words(self, words, stmt: ParsedStatement):
        """Extract movements using column positions detected dynamically from each page header."""
        col_info = self._detect_columns(words)
        if not col_info:
            return

        debit_center, credit_center, saldo_x0_thresh, desc_x0_max = col_info

        for row in self._group_words_by_row(words):
            # Date: DD.MM.YY in leftmost column
            date_words = [
                w for w in row
                if w["x0"] < self._DATE_X0_MAX
                and re.match(r"^\d{2}\.\d{2}\.\d{2}$", w["text"])
            ]
            if not date_words:
                continue

            # Description: words between desc min and the start of the debit column
            desc_words = sorted(
                [w for w in row if self._DESC_X0_MIN <= w["x0"] < desc_x0_max],
                key=lambda w: w["x0"],
            )
            if not desc_words:
                continue

            # End of the primary account section in an "Extrato Integrado":
            # subsequent rows belong to other accounts and would double-count
            # inter-account transfers.
            row_text_upper = " ".join(w["text"] for w in row).upper()
            if "SALDO" in row_text_upper and "CONTAB" in row_text_upper:
                self._stop_parsing = True
                break

            # Skip balance/total header rows
            if any(w["text"].upper() in ("SALDO", "TOTAL") for w in desc_words):
                continue

            # Amount candidates: PT-format numbers (d,dd or d.ddd,dd) to the right of desc zone
            amount_words = [
                w for w in row
                if w["x0"] >= desc_x0_max
                and re.match(r"^-?\d[\d.]*,\d{2}$", w["text"])
            ]

            debit_amount = None
            credit_amount = None
            balance = None

            for aw in amount_words:
                val = self.clean_amount(aw["text"])
                if aw["x0"] >= saldo_x0_thresh:
                    balance = val
                else:
                    center = (aw["x0"] + aw["x1"]) / 2
                    if abs(center - debit_center) <= abs(center - credit_center):
                        debit_amount = val
                    else:
                        credit_amount = val

            if debit_amount is None and credit_amount is None:
                continue

            amount = -abs(debit_amount) if debit_amount is not None else abs(credit_amount)
            date = self._parse_nb_date(date_words[0]["text"])
            if not date:
                continue

            stmt.movements.append(Movement(
                date=date,
                description=" ".join(w["text"] for w in desc_words).strip(),
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))

    def _detect_columns(self, words) -> tuple | None:
        """Find Débito/Crédito/Saldo column positions from the movement table header row."""
        for row in self._group_words_by_row(words):
            debito = next(
                (w for w in row if re.search(r"d.bito", w["text"], re.IGNORECASE) and w["x0"] > 300),
                None,
            )
            credito = next(
                (w for w in row if re.search(r"cr.dito", w["text"], re.IGNORECASE) and w["x0"] > 350),
                None,
            )
            saldo = next(
                (w for w in row if w["text"].lower() == "saldo" and w["x0"] > 400),
                None,
            )
            if debito and credito and saldo:
                debit_center = (debito["x0"] + debito["x1"]) / 2
                credit_center = (credito["x0"] + credito["x1"]) / 2
                saldo_x0_thresh = saldo["x0"] + 20  # balances start ~20-30px right of "Saldo" header
                desc_x0_max = debito["x0"] - 10     # description ends before debit column
                return debit_center, credit_center, saldo_x0_thresh, desc_x0_max
        return None

    def _group_words_by_row(self, words, y_tol: int = 2) -> list:
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

    def _parse_nb_date(self, date_str: str) -> str | None:
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})$", date_str)
        if not m:
            return None
        day, month, year2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{2000 + year2}-{month:02d}-{day:02d}"

    def _parse_nb_date_long(self, date_str: str) -> str | None:
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", date_str)
        if not m:
            return None
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
