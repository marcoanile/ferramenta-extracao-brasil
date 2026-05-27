"""Caixa Geral de Depósitos statement parser.

Handles two formats:
1. Digital export (Consultar saldos e movimentos) — pdfplumber layout
   - Dates: DD-MM-YYYY, listed newest-first
   - Period header: "Intervalo de DD-MM-YYYY a DD-MM-YYYY"
   - Movement rows: single line "DD-MM-YYYY  DD-MM-YYYY  origin  desc  amount  balance"

2. Printed/scanned statement (Extrato da Conta à Ordem) — pdfplumber layout
   - Dates: YYYY-MM-DD, listed oldest-first
   - Period header: "Período YYYY-MM-DD a YYYY-MM-DD"

3. Digital export extracted via PyMuPDF (fallback when pdfplumber raises EOF)
   - Same DD-MM-YYYY / newest-first structure
   - BUT each column is on its own line:
       DD-MM-YYYY
       DD-MM-YYYY
       ORIGIN
       Description line 1
       [Description line 2 ...]
       ±amount   (e.g. -431,71)
       balance   (e.g. 9.582,33)
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
        "conta extracto",   # digital export header
    ]

    _PT_NUM = re.compile(r'-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}')

    # Movement line patterns — two dates at start (pdfplumber single-line format)
    _ROW_ISO = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})\s')   # YYYY-MM-DD
    _ROW_DMY = re.compile(r'^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s')   # DD-MM-YYYY

    # Strip either date format from head of string
    _DATE_PREFIX = re.compile(r'^\d{2,4}-\d{2}-\d{2,4}\s+')

    # Bare date line (PyMuPDF multi-line format) — exactly a date, nothing else
    _BARE_DATE_DMY = re.compile(r'^\d{2}-\d{2}-\d{4}$')
    _BARE_DATE_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')

    # Standalone Portuguese-format number (amount or balance on its own line)
    _BARE_PT_NUM = re.compile(r'^-?\d{1,3}(?:\.\d{3})*,\d{2}$')

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        combined = text.lower() + filename.lower()
        return any(s in combined for s in self.SIGNATURES)

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        self._extract_header(text, stmt)

        # Try the single-line format first (pdfplumber output)
        newest_first = self._extract_movements(text, stmt)

        # If nothing found, try the multi-line block format (PyMuPDF output)
        if not stmt.movements:
            newest_first = self._extract_movements_multiline(text, stmt)

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
        """Parse single-line movement rows (pdfplumber output).
        Returns True if movements are newest-first (needs reversal)."""
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

    def _extract_movements_multiline(self, text: str, stmt: ParsedStatement) -> bool:
        """Parse multi-line movement blocks (PyMuPDF output).

        In this format each column of the bank table lands on its own line:
            DD-MM-YYYY          ← date mov
            DD-MM-YYYY          ← date valor
            ORIGIN              ← 2-4 char code (EXCI, LCRT, 0003, SIBS …)
            Description part 1
            [Description part 2]
            [Description part 3]
            ±amount             ← signed PT number, e.g. -431,71
            9.582,33            ← balance (always positive)

        Two consecutive bare-date lines signal the start of a new record.
        Returns True (newest-first) if DD-MM-YYYY dates found, False for ISO.
        """
        lines = [l.strip() for l in text.splitlines()]
        n = len(lines)

        def is_bare_dmy(s):
            return bool(self._BARE_DATE_DMY.match(s))

        def is_bare_iso(s):
            return bool(self._BARE_DATE_ISO.match(s))

        def is_bare_num(s):
            return bool(self._BARE_PT_NUM.match(s))

        # Detect date style from first matching pair
        date_style = None  # 'dmy' or 'iso'
        for i in range(n - 1):
            if is_bare_dmy(lines[i]) and is_bare_dmy(lines[i + 1]):
                date_style = 'dmy'
                break
            if is_bare_iso(lines[i]) and is_bare_iso(lines[i + 1]):
                date_style = 'iso'
                break

        if date_style is None:
            return False

        is_bare_date = is_bare_dmy if date_style == 'dmy' else is_bare_iso
        newest_first = (date_style == 'dmy')

        # Collect blocks: each starts with two consecutive date lines
        block_starts = []
        i = 0
        while i < n - 1:
            if is_bare_date(lines[i]) and is_bare_date(lines[i + 1]):
                block_starts.append(i)
                i += 2  # skip both dates to avoid re-matching on lines[i+1]
            else:
                i += 1

        for b, start in enumerate(block_starts):
            end = block_starts[b + 1] if b + 1 < len(block_starts) else n
            block = lines[start:end]

            if len(block) < 4:
                continue  # need date, date, amount, balance at minimum

            date_str = self.parse_date(block[0])
            if not date_str:
                continue

            # Find all bare PT numbers in the block (from index 2 onward)
            num_indices = [
                j for j in range(2, len(block))
                if is_bare_num(block[j])
            ]

            if len(num_indices) < 2:
                continue

            # Last two bare numbers are amount and balance
            amount_idx = num_indices[-2]
            balance_idx = num_indices[-1]
            amount = self.clean_amount(block[amount_idx])
            balance = self.clean_amount(block[balance_idx])

            # Description: lines between the two dates and the amount line
            desc_parts = [
                block[j] for j in range(2, amount_idx)
                if block[j] and not is_bare_date(block[j])
            ]
            desc = ' '.join(desc_parts).strip()
            if not desc:
                continue

            stmt.movements.append(Movement(
                date=date_str,
                description=desc,
                amount=amount,
                balance=balance,
                movement_type="debit" if amount < 0 else "credit",
            ))

        return newest_first
