import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
SEED_DIR = Path(__file__).parent / "seed"

TOCONLINE_CLIENT_ID = os.getenv("TOCONLINE_CLIENT_ID", "")
TOCONLINE_CLIENT_SECRET = os.getenv("TOCONLINE_CLIENT_SECRET", "")
TOCONLINE_OAUTH_URL = os.getenv("TOCONLINE_OAUTH_URL", "https://identity.toconline.pt")
TOCONLINE_API_URL = os.getenv("TOCONLINE_API_URL", "https://apiv1.toconline.com")

CEGID_API_URL = os.getenv("CEGID_API_URL", "")
CEGID_API_KEY = os.getenv("CEGID_API_KEY", "")

SECRET_KEY = os.getenv("SECRET_KEY", "nexus-accounting-secret")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

CLIENTS_DIR = DATA_DIR / "clients"
TEMPLATES_DIR = DATA_DIR / "templates"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "nexus.db"

for d in [DATA_DIR, CLIENTS_DIR, TEMPLATES_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Seed the TOConline import template into the (possibly empty) templates dir.
# On Render the data dir is a fresh persistent disk on first boot.
if SEED_DIR.exists():
    for seed_file in SEED_DIR.glob("*"):
        target = TEMPLATES_DIR / seed_file.name
        if not target.exists():
            shutil.copy2(seed_file, target)

SUPPORTED_BANKS = [
    "Millennium BCP",
    "BPI",
    "Caixa Geral de Depósitos",
    "Santander",
    "Novo Banco",
    "BIC / Eurobic",
    "Montepio",
    "Activobank",
    "Genérico",
]

SUPPORTED_FORMATS = [".pdf", ".xlsx", ".xls", ".csv"]
