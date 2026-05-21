"""BPI bank statement parser — handles BPI Extrato de Conta PDF format.

Format per page:
  DATA MOV  DATA VAL  DESCRIÇÃO DO MOVIMENTO  MOEDA  VALOR  SALDO
Lines start with DD/MM, may have 1-3 leading dates, then description, then
signed amount and unsigned balance (Portuguese decimal format, space thousands sep).
"""
import re
from datetime import datetime
from .base import BankParser, ParsedStatement, Movement


class BPIParser(BankParser):
    bank_name = "BPI"
    SIGNATURES = ["banco bpi", "bbpiptpl", "extracto de conta", "bpi.pt"]

    # Portuguese number: optional minus, 1-3 digits, optional (space + 3 digits) groups, comma + 2 decimal
    _PT_NUM = re.compile(r'-?(?:\d{1,3}(?:[ ]\d{3})*|\d+),\d{2}')

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        return any(s in (text + filename).lower() for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        year = self._extract_year(text)
        self._extract_header(text, stmt)
        self._extract_movements(text, stmt, year)
        if stmt.movements and not stmt.closing_balance:
            stmt.closing_balance = stmt.movements[-1].balance
        return stmt

    def _extract_year(self, text: str) -> int:
        # First full DD/MM/YYYY date in the document gives the statement year
        m = re.search(r'\d{2}/\d{2}/(\d{4})', text)
        if m:
            return int(m.group(1))
        return datetime.now().year

    def _extract_header(self, text: str, stmt: ParsedStatement):
        # IBAN
        m = re.search(r'IBAN[:\s]+([A-Z]{2}[\d\s]{20,30})', text)
        if m:
            stmt.iban = re.sub(r'\s+', '', m.group(1))[:27]

        # Period: "Período De DD/MM/YYYY a DD/MM/YYYY"
        m = re.search(
            r'(?:Per[ií]odo|Per.odo)\s+[Dd]e\s+(\d{2}/\d{2}/\d{4})\s+[Aa]\s+(\d{2}/\d{2}/\d{4})',
            text, re.IGNORECASE
        )
        if m:
            stmt.period_start = self.parse_date(m.group(1))
            stmt.period_end = self.parse_date(m.group(2))

        # Opening balance: "SALDO ANTERIOR CONTABILISTICO 93 377,40"
        m = re.search(r'SALDO ANTERIOR[^\d]*([\d ]+,\d{2})', text, re.IGNORECASE)
        if m:
            stmt.opening_balance = self.clean_amount(m.group(1))

    def _extract_movements(self, text: str, stmt: ParsedStatement, year: int):
        for line in text.splitlines():
            line = line.strip()
            # Lines must start with DD/MM followed by whitespace
            if not re.match(r'^\d{2}/\d{2}\s', line):
                continue

            # Find all Portuguese-format numbers on the line
            nums = list(self._PT_NUM.finditer(line))
            if len(nums) < 2:
                continue

            # Last = balance, second-to-last = amount
            amount_match = nums[-2]
            amount = self.clean_amount(amount_match.group())
            balance = self.clean_amount(nums[-1].group())

            # Everything before the amount is leading dates + description
            head = line[:amount_match.start()].strip()

            # Strip leading DD/MM dates (1 to 3 dates)
            mov_date = None
            for _ in range(3):
                m = re.match(r'^(\d{2}/\d{2})\s+', head)
                if not m:
                    break
                if mov_date is None:
                    mov_date = m.group(1)
                head = head[m.end():]

            if not mov_date or not head.strip():
                continue

            try:
                day, month = int(mov_date[:2]), int(mov_date[3:5])
                date_str = f"{year}-{month:02d}-{day:02d}"
            except (ValueError, IndexError):
                continue

            stmt.movements.append(Movement(
                date=date_str,
                description=head.strip(),
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))
