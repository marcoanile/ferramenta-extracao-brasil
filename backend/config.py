import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
SEED_DIR = Path(__file__).parent / "seed"

SECRET_KEY = os.getenv("SECRET_KEY", "nexus-accounting-secret")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

TEMPLATES_DIR = DATA_DIR / "templates"
LOGS_DIR = DATA_DIR / "logs"
TEMP_DIR = DATA_DIR / "temp"
DB_PATH = DATA_DIR / "nexus.db"

SUPPORTED_FORMATS = [".pdf", ".xlsx", ".xls", ".csv"]

for d in [DATA_DIR, TEMPLATES_DIR, LOGS_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Copy bundled template into the templates dir on first boot (e.g. Render fresh disk).
if SEED_DIR.exists():
    for seed_file in SEED_DIR.glob("*"):
        target = TEMPLATES_DIR / seed_file.name
        if not target.exists():
            shutil.copy2(seed_file, target)
