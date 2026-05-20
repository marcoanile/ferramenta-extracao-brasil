"""Crédito Agrícola statement parser (PDF web export — Consulta de Movimentos)."""
import re
from .base import BankParser, ParsedStatement, Movement


class CreditoAgricolaParser(BankParser):
    bank_name = "Crédito Agrícola"

    SIGNATURES = [
        "consulta de movimentos de contas d.o",  # title on every page — very specific
        "creditoagricola.pt",
        "credito agric",                          # covers "crédito agrícola" and encoding variants
        "caixa central de cred",
    ]

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        text_lower = text.lower() + filename.lower()
        return any(s in text_lower for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        self._extract_movements(text, stmt)
        # Opening = balance before the first chronological movement.
        # movements[-1] is first chronological (PDF is reverse-chron).
        if stmt.movements:
            first = stmt.movements[-1]
            stmt.opening_balance = round(first.balance - first.amount, 2)
        return stmt

    def _extract_header(self, text: str, stmt: ParsedStatement):
        # Account number
        acc_m = re.search(r"N[uú]mero\s+de\s+Conta[:\s]+([\d]+)", text, re.IGNORECASE)
        if acc_m:
            stmt.account_number = acc_m.group(1)

        # Period: "De: 31/08/2025"  "A: 30/09/2025"
        de_m = re.search(r"^De[:\s]+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE | re.MULTILINE)
        a_m  = re.search(r"^A[:\s]+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE | re.MULTILINE)
        if de_m:
            stmt.period_start = self._parse_pt_date(de_m.group(1))
        if a_m:
            stmt.period_end = self._parse_pt_date(a_m.group(1))

    def _extract_movements(self, text: str, stmt: ParsedStatement):
        # Pattern: DD/MM/YYYY DD/MM/YYYY description [-] amount EUR D/C balance EUR
        # Amounts use PT format: dots as thousands, comma as decimal
        pattern = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(?:-\s)?"
            r"([\d]+(?:\.\d{3})*,\d{2})\s+([DC])\s+([\d]+(?:\.\d{3})*,\d{2})\s*$",
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            date_str, _valor, desc, amount_str, dc, balance_str = m.groups()
            date = self._parse_pt_date(date_str)
            if not date:
                continue
            amount = self.clean_amount(amount_str)
            if dc == "D":
                amount = -abs(amount)
            stmt.movements.append(Movement(
                date=date,
                description=desc.strip(),
                amount=amount,
                balance=self.clean_amount(balance_str),
                movement_type="debit" if amount < 0 else "credit",
            ))

        # PDF is reverse-chronological: movements[0] = last chronological = true closing balance.
        # Do NOT use max(balance) — intra-day balance can temporarily exceed the final balance.
        if stmt.movements:
            stmt.closing_balance = stmt.movements[0].balance

    def _parse_pt_date(self, date_str: str) -> str | None:
        """Parse DD/MM/YYYY to YYYY-MM-DD."""
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", date_str)
        if not m:
            return None
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
