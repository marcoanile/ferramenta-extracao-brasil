"""Generic fallback parser — handles most tabular CSV/Excel exports."""
import re
from .base import BankParser, ParsedStatement, Movement


class GenericParser(BankParser):
    bank_name = "Genérico"

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        return True  # always fallback

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
        stmt = ParsedStatement(bank_name=self.bank_name)
        stmt.warnings.append("Banco não reconhecido automaticamente — utilizando parser genérico.")
        self._extract_movements(text, stmt)
        return stmt

    def _extract_movements(self, text: str, stmt: ParsedStatement):
        # Looks for lines with a date + amount pattern
        pattern = re.compile(
            r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\s+"
            r"(.{3,80}?)\s+"
            r"(-?[\d.,]+)\s*"
            r"(-?[\d.,]+)?",
            re.MULTILINE
        )
        for m in pattern.finditer(text):
            groups = m.groups()
            date_str = groups[0]
            desc = groups[1].strip() if groups[1] else ""
            amount_str = groups[2]
            balance_str = groups[3]
            amount = self.clean_amount(amount_str)
            mov = Movement(
                date=self.parse_date(date_str),
                description=desc,
                amount=amount,
                balance=self.clean_amount(balance_str) if balance_str else None,
                movement_type="debit" if amount < 0 else "credit",
            )
            if mov.date and desc:
                stmt.movements.append(mov)
