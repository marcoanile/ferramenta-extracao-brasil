"""Auto-detect bank format from file content."""
from .banks.millennium import MillenniumParser
from .banks.bpi import BPIParser
from .banks.cgd import CGDParser
from .banks.santander import SantanderParser
from .banks.novobanco import NovoBancoParser
from .banks.bankinter import BankinterParser
from .banks.credito_agricola import CreditoAgricolaParser
from .banks.generic import GenericParser

PARSERS = [
    NovoBancoParser(),       # SWIFT "bescptpl" is unique
    BankinterParser(),       # SWIFT "bkbkptpl" is unique
    SantanderParser(),       # SWIFT "totaptpl" is unique
    CreditoAgricolaParser(), # "consulta de movimentos de contas d.o" is very specific
    BPIParser(),
    MillenniumParser(),
    CGDParser(),             # last real bank — its signatures are now tighter
    GenericParser(),         # must be last
]


def detect_parser(content: str | bytes, filename: str):
    """Return the best parser for the given content/filename."""
    for parser in PARSERS:
        if parser.can_parse(content, filename):
            return parser
    return GenericParser()


def detect_bank_name(content: str | bytes, filename: str) -> str:
    return detect_parser(content, filename).bank_name
