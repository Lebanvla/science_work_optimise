from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


SERVER_DIR = Path(__file__).resolve().parent
load_dotenv(SERVER_DIR / ".env")

STORAGE_DIR = SERVER_DIR / "storage"
INPUT_DIR = STORAGE_DIR / "input"
OUTPUT_DIR = STORAGE_DIR / "output"
TEMPLATES_DIR = SERVER_DIR / "templates"

_db_path = os.getenv("DB_PATH")
DB_PATH = Path(_db_path) if _db_path else STORAGE_DIR / "tasks.db"
if not DB_PATH.is_absolute():
    DB_PATH = (SERVER_DIR / DB_PATH).resolve()

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024)))


WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")


CLEANUP_INPUT_DELAY_SECONDS = int(os.getenv("CLEANUP_INPUT_DELAY_SECONDS", "600"))
CLEANUP_OUTPUT_DELAY_SECONDS = int(os.getenv("CLEANUP_OUTPUT_DELAY_SECONDS", "3600"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "60"))
TASK_STALE_SECONDS = int(os.getenv("TASK_STALE_SECONDS", "1800"))


def ensure_directories() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)