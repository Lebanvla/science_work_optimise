from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from config import (
    API_BASE_URL,
    POLL_INTERVAL_SECONDS,
    TMP_DIR,
    WORKER_TOKEN,
)
from model_runner import SegFormerCityscapesModel, process_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

HEADERS = {"Authorization": f"Bearer {WORKER_TOKEN}"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch_pending() -> dict | None:
    r = SESSION.get(f"{API_BASE_URL}/worker/tasks/pending", timeout=30)
    r.raise_for_status()
    return r.json().get("task")


def download_input(task_id: int, dest: Path) -> None:
    with SESSION.get(f"{API_BASE_URL}/worker/tasks/{task_id}/image", stream=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                f.write(chunk)


def upload_result(task_id: int, path: Path) -> None:
    with path.open("rb") as f:
        r = SESSION.post(
            f"{API_BASE_URL}/worker/tasks/{task_id}/result",
            files={"file": (path.name, f, "image/png")},
            timeout=120,
        )
    r.raise_for_status()


def report_failure(task_id: int, message: str) -> None:
    try:
        SESSION.post(
            f"{API_BASE_URL}/worker/tasks/{task_id}/fail",
            json={"message": message[:500]},
            timeout=30,
        ).raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to report failure for task %s", task_id)


def handle_task(task: dict, model: SegFormerCityscapesModel) -> None:
    task_id = int(task["id"])
    input_path = TMP_DIR / f"task_{task_id}_input"
    output_path = TMP_DIR / f"task_{task_id}_output.png"

    try:
        logger.info("Picked task id=%s hash=%s", task_id, task.get("picture_hash"))
        download_input(task_id, input_path)
        process_image(str(input_path), str(output_path), model)
        upload_result(task_id, output_path)
        logger.info("Task id=%s done", task_id)
    except Exception as exc:
        logger.exception("Task id=%s failed", task_id)
        report_failure(task_id, str(exc))
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def main() -> None:
    if not WORKER_TOKEN:
        raise SystemExit("WORKER_TOKEN is empty; set it in worker/.env")

    logger.info("Worker starting, API=%s", API_BASE_URL)
    logger.info("Loading model once at startup")
    model = SegFormerCityscapesModel()
    logger.info("Model is ready")

    while True:
        try:
            task = fetch_pending()
        except requests.RequestException:
            logger.exception("Failed to fetch pending task, sleeping")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if task is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        handle_task(task, model)


if __name__ == "__main__":
    main()