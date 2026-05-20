"""Base class for all bank statement parsers."""
import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Movement:
    date: str               # ISO format YYYY-MM-DD
    description: str
    amount: float           # negative = debit, positive = credit
    balance: Optional[float] = None
    reference: Optional[str] = None
    movement_type: Optional[str] = None   # "debit" | "credit"
    category: Optional[str] = None

    def hash_key(self, client_id: int) -> str:
        raw = f"{client_id}|{self.date}|{self.description}|{self.amount}"
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class ParsedStatement:
    bank_name: str
    iban: Optional[str] = None
    account_number: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    movements: list[Movement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def sorted_movements(self) -> list[Movement]:
        return sorted(self.movements, key=lambda m: m.date)


class BankParser:
    bank_name = "Genérico"

    def can_parse(self, content: str | bytes, filename: str) -> bool:
        """Return True if this parser handles the given content."""
        raise NotImplementedError

    def parse(self, content: str | bytes, filename: str) -> ParsedStatement:
        raise NotImplementedError

    @staticmethod
    def clean_amount(value: str) -> float:
        """Convert Portuguese formatted number string to float."""
        if not value:
            return 0.0
        v = str(value).strip().replace(" ", "").replace("\xa0", "")
        if v.lower() in ("nan", "none", "n/a", "-", ""):
            return 0.0
        # Handle debit/credit suffix
        is_negative = v.startswith("-") or v.endswith("-") or v.startswith("(")
        v = v.replace("(", "").replace(")", "").replace("-", "").replace("+", "")
        # Portuguese: 1.234,56 -> 1234.56
        if "," in v and "." in v:
            if v.index(".") < v.index(","):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")
        elif "," in v:
            v = v.replace(",", ".")
        try:
            result = float(v)
        except ValueError:
            return 0.0
        return -result if is_negative else result

    @staticmethod
    def parse_date(value: str) -> str | None:
        """Parse various Portuguese date formats to YYYY-MM-DD."""
        from dateutil import parser as dparser
        import re
        if not value:
            return None
        value = str(value).strip()
        # DD-MM-YYYY or DD/MM/YYYY
        m = re.match(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})", value)
        if m:
            d, mo, y = m.groups()
            y = f"20{y}" if len(y) == 2 else y
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        try:
            return dparser.parse(value, dayfirst=True).strftime("%Y-%m-%d")
        except Exception:
            return None
