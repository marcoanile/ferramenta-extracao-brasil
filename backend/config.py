import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent

# Load project-root .env first (local dev defaults)
load_dotenv(BASE_DIR / ".env")

# DATA_DIR comes from real env var (set by Render) or falls back to ../data
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))

# Overlay with disk-persisted .env so runtime-saved credentials survive restarts
_disk_env = DATA_DIR / ".env"
if _disk_env.exists():
    load_dotenv(_disk_env, override=True)

TOCONLINE_CLIENT_ID = os.getenv("TOCONLINE_CLIENT_ID", "")
TOCONLINE_CLIENT_SECRET = os.getenv("TOCONLINE_CLIENT_SECRET", "")
TOCONLINE_OAUTH_URL = os.getenv("TOCONLINE_OAUTH_URL", "https://identity.toconline.pt")
TOCONLINE_API_URL = os.getenv("TOCONLINE_API_URL", "https://apiv1.toconline.com")

CEGID_API_URL = os.getenv("CEGID_API_URL", "")
CEGID_API_KEY = os.getenv("CEGID_API_KEY", "")

SECRET_KEY = os.getenv("SECRET_KEY") or __import__("secrets").token_hex(32)
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

CLIENTS_DIR = DATA_DIR / "clients"
TEMPLATES_DIR = DATA_DIR / "templates"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "nexus.db"

for d in [DATA_DIR, CLIENTS_DIR, TEMPLATES_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

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
