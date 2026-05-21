"""Santander Totta statement parser."""
import re
from .base import BankParser, ParsedStatement, Movement


class SantanderParser(BankParser):
    bank_name = "Santander"

    SIGNATURES = ["banco santander totta", "banco santander", "totta", "totaptpl"]

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        text_lower = text.lower() + filename.lower()
        return any(s in text_lower for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        self._extract_movements(text, stmt)
        return stmt

    def _extract_header(self, text: str, stmt: ParsedStatement):
        # IBAN: "IBAN: PT50001800035534264602007"
        iban_m = re.search(r"IBAN[:\s]+(PT\d{23})", text, re.IGNORECASE)
        if iban_m:
            stmt.iban = iban_m.group(1)
        else:
            iban_m = re.search(r"PT\d{2}[\d ]{20,}", text)
            if iban_m:
                stmt.iban = iban_m.group(0).replace(" ", "")[:25]

        # Period: "PERÍODO DE 2025-01-01 A 2025-01-31"
        period_m = re.search(
            r"PER.ODO\s+DE\s+(\d{4}-\d{2}-\d{2})\s+A\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE
        )
        if period_m:
            stmt.period_start = period_m.group(1)
            stmt.period_end = period_m.group(2)

        # Opening: "Saldo Inicial EUR 934,63"
        bal_m = re.search(r"Saldo\s+Inicial\s+(?:EUR\s+)?(-?[\d.,]+)", text, re.IGNORECASE)
        if bal_m:
            stmt.opening_balance = self.clean_amount(bal_m.group(1))

        # Closing: "Saldo Contabilístico Final EUR -15,67"
        cbal_m = re.search(r"Saldo\s+Contabil[^\s]*\s+Final\s+(?:EUR\s+)?(-?[\d.,]+)", text, re.IGNORECASE)
        if cbal_m:
            stmt.closing_balance = self.clean_amount(cbal_m.group(1))

    def _extract_movements(self, text: str, stmt: ParsedStatement):
        year_m = re.search(r"PER.ODO\s+DE\s+(\d{4})", text, re.IGNORECASE)
        year = int(year_m.group(1)) if year_m else None

        # Each line: DD-MM DD-MM description  signed_amount  balance
        # Amounts use PT format (comma decimal, optional leading minus)
        pattern = re.compile(
            r"^(\d{2}-\d{2})\s+(\d{2}-\d{2})\s+(.+?)\s+(-?[\d.]*\d+,\d{2})\s+(-?[\d.,]+)\s*$",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            date_lanc, _date_valor, desc, amount_str, balance_str = m.groups()
            date = self._parse_date(date_lanc, year)
            if not date:
                continue
            amount = self.clean_amount(amount_str)
            balance = self.clean_amount(balance_str)
            stmt.movements.append(Movement(
                date=date,
                description=desc.strip(),
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))

    def _parse_date(self, date_str: str, year: int = None) -> str | None:
        """Parse DD-MM to YYYY-MM-DD using year from statement header."""
        m = re.match(r"^(\d{2})-(\d{2})$", date_str)
        if not m:
            return None
        day, month = int(m.group(1)), int(m.group(2))
        if year is None:
            from datetime import date
            year = date.today().year
        return f"{year}-{month:02d}-{day:02d}"
