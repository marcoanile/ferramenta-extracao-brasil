"""Bankinter statement parser (PDF)."""
import re
from .base import BankParser, ParsedStatement, Movement


class BankinterParser(BankParser):
    bank_name = "Bankinter"

    SIGNATURES = ["bankinter", "bkbkptpl", "bankinter.pt", "bankinter.com"]

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
        # PT IBAN: PT + 23 digits (stop before SWIFT/BIC)
        iban_m = re.search(r"IBAN[:\s]+(PT\d{2}(?:\s*\d{4}){5}\s*\d{1,3})", text, re.IGNORECASE)
        if iban_m:
            stmt.iban = re.sub(r"\s+", "", iban_m.group(1))

        period_m = re.search(
            r"de\s+(\d{4}/\d{2}/\d{2})\s+a\s+(\d{4}/\d{2}/\d{2})", text, re.IGNORECASE
        )
        if period_m:
            stmt.period_start = period_m.group(1).replace("/", "-")
            stmt.period_end = period_m.group(2).replace("/", "-")

        # "Saldo em 2025/12/01 61.962,23" — first = opening, last = closing
        all_bals = re.findall(r"Saldo\s+em\s+\d{4}/\d{2}/\d{2}\s+([\d.,]+)", text, re.IGNORECASE)
        if all_bals:
            stmt.opening_balance = self.clean_amount(all_bals[0])
        if len(all_bals) >= 2:
            stmt.closing_balance = self.clean_amount(all_bals[-1])

    def _extract_movements(self, text: str, stmt: ParsedStatement):
        year_m = re.search(r"de\s+(\d{4})/\d{2}/\d{2}", text, re.IGNORECASE)
        year = int(year_m.group(1)) if year_m else None

        # Each movement line: DD/MM  description  DD/MM  ±amount  balance
        pattern = re.compile(
            r"^(\d{2}/\d{2})\s+(.+?)\s+(\d{2}/\d{2})\s+(-?[\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            date_lanc, desc, _date_valor, amount_str, balance_str = m.groups()
            day, month = date_lanc.split("/")
            date = f"{year}-{int(month):02d}-{int(day):02d}" if year else None
            if not date:
                continue
            amount = self.clean_amount(amount_str)
            balance = self.clean_amount(balance_str)
            mov = Movement(
                date=date,
                description=desc.strip(),
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            )
            stmt.movements.append(mov)
