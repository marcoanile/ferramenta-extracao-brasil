"""Caixa Geral de Depósitos statement parser.

Handles two formats:
1. Digital export (Consultar saldos e movimentos)
   - Dates: DD-MM-YYYY, listed newest-first
   - Period header: "Intervalo de DD-MM-YYYY a DD-MM-YYYY"

2. Printed/scanned statement (Extrato da Conta à Ordem)
   - Dates: YYYY-MM-DD, listed oldest-first
   - Period header: "Período YYYY-MM-DD a YYYY-MM-DD"
"""
import re
from .base import BankParser, ParsedStatement, Movement


class CGDParser(BankParser):
    bank_name = "Caixa Geral de Depósitos"

    SIGNATURES = [
        "caixa geral de dep",
        "caixadirecta",
        "cgd.pt",
        "cgdiptpl",          # SWIFT/BIC on printed statements
        "extrato da conta",
        "conta a ordem",
        "conta à ordem",
    ]

    _PT_NUM = re.compile(r'-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}')

    # Movement line patterns — two dates at start
    _ROW_ISO = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})\s')   # YYYY-MM-DD
    _ROW_DMY = re.compile(r'^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s')   # DD-MM-YYYY

    # Strip either date format from head of string
    _DATE_PREFIX = re.compile(r'^\d{2,4}-\d{2}-\d{2,4}\s+')

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        combined = text.lower() + filename.lower()
        return any(s in combined for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        newest_first = self._extract_movements(text, stmt)
        if not stmt.movements:
            return stmt
        if newest_first:
            stmt.movements.reverse()
        stmt.closing_balance = stmt.movements[-1].balance
        first = stmt.movements[0]
        stmt.opening_balance = round(first.balance - first.amount, 2)
        return stmt

    def _extract_header(self, text: str, stmt: ParsedStatement):
        # Digital: "Intervalo de DD-MM-YYYY a DD-MM-YYYY"
        m = re.search(
            r'Intervalo\s+de\s+(\d{2}-\d{2}-\d{4})\s+[Aa]\s+(\d{2}-\d{2}-\d{4})',
            text, re.IGNORECASE,
        )
        if m:
            stmt.period_start = self.parse_date(m.group(1))
            stmt.period_end = self.parse_date(m.group(2))
            return

        # Printed/scanned: "Período YYYY-MM-DD a YYYY-MM-DD"
        m = re.search(
            r'Per[^\s]*odo\s+(\d{4}-\d{2}-\d{2})\s+[Aa]\s+(\d{4}-\d{2}-\d{2})',
            text, re.IGNORECASE,
        )
        if m:
            stmt.period_start = self.parse_date(m.group(1))
            stmt.period_end = self.parse_date(m.group(2))

        # Account number (digital format)
        m = re.search(r'Conta\s+([\d]+)\s+-\s+EUR', text)
        if m:
            stmt.account_number = m.group(1)

    def _extract_movements(self, text: str, stmt: ParsedStatement) -> bool:
        """Parse movement lines. Returns True if movements are newest-first (needs reversal)."""
        newest_first = False
        for line in text.splitlines():
            line = line.strip()

            iso_m = self._ROW_ISO.match(line)
            dmy_m = self._ROW_DMY.match(line)

            if dmy_m:
                newest_first = True
                date_str = self.parse_date(dmy_m.group(1))
            elif iso_m:
                date_str = self.parse_date(iso_m.group(1))
            else:
                continue

            nums = list(self._PT_NUM.finditer(line))
            if len(nums) < 2:
                continue

            amount_m = nums[-2]
            balance_m = nums[-1]
            amount = self.clean_amount(amount_m.group())
            balance = self.clean_amount(balance_m.group())

            # Strip the two leading dates to isolate description
            head = line
            for _ in range(2):
                m = self._DATE_PREFIX.match(head)
                if m:
                    head = head[m.end():]

            stripped = len(line) - len(head)
            desc = head[:amount_m.start() - stripped].strip()
            if not desc or not date_str:
                continue

            stmt.movements.append(Movement(
                date=date_str,
                description=desc,
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))

        return newest_first
