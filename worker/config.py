from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

WORKER_DIR = Path(__file__).resolve().parent
load_dotenv(WORKER_DIR / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "nvidia/segformer-b0-finetuned-cityscapes-768-768",
)
ROAD_CLASS_NAME = os.getenv("ROAD_CLASS_NAME", "road")
ROAD_CLASS_INDEX = os.getenv("ROAD_CLASS_INDEX")
DEVICE = os.getenv("DEVICE", "auto")

TMP_DIR = WORKER_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)