"""File storage helpers — organise client files on disk."""
from pathlib import Path
import config


def client_dir(client_id: int) -> Path:
    d = config.CLIENTS_DIR / str(client_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def statements_dir(client_id: int) -> Path:
    d = client_dir(client_id) / "statements"
    d.mkdir(parents=True, exist_ok=True)
    return d


def converted_dir(client_id: int) -> Path:
    d = client_dir(client_id) / "converted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(client_id: int) -> Path:
    d = client_dir(client_id) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_client_files(client_id: int) -> dict:
    """Return dict of {type: [paths]} for a client."""
    base = client_dir(client_id)
    return {
        "statements": [str(p) for p in (base / "statements").glob("*") if p.is_file()],
        "converted": [str(p) for p in (base / "converted").glob("*.xlsx") if p.is_file()],
        "logs": [str(p) for p in (base / "logs").glob("*") if p.is_file()],
    }
