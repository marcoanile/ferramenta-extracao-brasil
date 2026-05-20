"""Caixa Geral de Depósitos statement parser.

CGD online export (Consultar saldos e movimentos) format:
  Row header: "Data mov. Data-valor Descrição Montante Saldo contabilístico após movimento"
  Data rows:  DD-MM-YYYY  DD-MM-YYYY  DESCRIPTION  AMOUNT  BALANCE
              (optional continuation line with truncated description — ignored)

Movements are listed newest-first; parser reverses to chronological order.
Amounts are signed (negative=debit), Portuguese format with period-thousands and comma-decimal.
"""
import re
from .base import BankParser, ParsedStatement, Movement


class CGDParser(BankParser):
    bank_name = "Caixa Geral de Depósitos"

    # ASCII-safe signatures that survive pdfplumber encoding corruption
    SIGNATURES = [
        "caixa geral de dep",   # "Caixa Geral de Dep?sitos" partial
        "caixadirecta",
        "cgd.pt",
    ]

    # Portuguese number: optional minus, integer part (with period-thousands), comma + 2 decimals
    _PT_NUM = re.compile(r'-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}')

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        combined = text.lower() + filename.lower()
        return any(s in combined for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)
        self._extract_movements(text, stmt)
        return stmt

    def _extract_header(self, text: str, stmt: ParsedStatement):
        # Period: "Intervalo de DD-MM-YYYY a DD-MM-YYYY"
        m = re.search(
            r'Intervalo\s+de\s+(\d{2}-\d{2}-\d{4})\s+[Aa]\s+(\d{2}-\d{2}-\d{4})',
            text, re.IGNORECASE
        )
        if m:
            stmt.period_start = self.parse_date(m.group(1))
            stmt.period_end = self.parse_date(m.group(2))

        # Account number
        m = re.search(r'Conta\s+([\d]+)\s+-\s+EUR', text)
        if m:
            stmt.account_number = m.group(1)

    def _extract_movements(self, text: str, stmt: ParsedStatement):
        for line in text.splitlines():
            line = line.strip()

            # Line must start with two DD-MM-YYYY dates
            if not re.match(r'^\d{2}-\d{2}-\d{4}\s+\d{2}-\d{2}-\d{4}\s', line):
                continue

            # Find all Portuguese-format numbers on this line
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
                m = re.match(r'^\d{2}-\d{2}-\d{4}\s+', head)
                if m:
                    head = head[m.end():]

            # Description = head up to where the amount starts (adjusted for stripped prefix)
            stripped = len(line) - len(head)
            desc = head[:amount_m.start() - stripped].strip()
            if not desc:
                continue

            date_m = re.match(r'^(\d{2}-\d{2}-\d{4})', line)
            date_str = self.parse_date(date_m.group(1)) if date_m else None
            if not date_str:
                continue

            stmt.movements.append(Movement(
                date=date_str,
                description=desc,
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))

        if not stmt.movements:
            return

        # CGD lists newest-first — reverse to chronological order
        stmt.movements.reverse()
        stmt.closing_balance = stmt.movements[-1].balance
        # Opening = first movement's post-balance minus its amount
        first = stmt.movements[0]
        stmt.opening_balance = round(first.balance - first.amount, 2)
