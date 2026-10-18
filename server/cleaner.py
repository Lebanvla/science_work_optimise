from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from config import (
    CLEANUP_INPUT_DELAY_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    CLEANUP_OUTPUT_DELAY_SECONDS,
    TASK_STALE_SECONDS,
)
from database import get_conn

logger = logging.getLogger(__name__)


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to unlink %s", path)


def _cleanup_once() -> None:
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE tasks
               SET status = 'pending', started_at = NULL
             WHERE status = 'processing'
               AND started_at IS NOT NULL
               AND datetime(started_at) < datetime('now', '-{int(TASK_STALE_SECONDS)} seconds')
            """
        )

        rows = conn.execute(
            f"""
            SELECT id, input_path FROM tasks
             WHERE input_path IS NOT NULL
               AND status IN ('done', 'failed')
               AND completed_at IS NOT NULL
               AND datetime(completed_at) < datetime('now', '-{int(CLEANUP_INPUT_DELAY_SECONDS)} seconds')
            """
        ).fetchall()
        for row in rows:
            _safe_unlink(row["input_path"])
            conn.execute("UPDATE tasks SET input_path = NULL WHERE id = ?", (row["id"],))

        rows = conn.execute(
            f"""
            SELECT id, result_path FROM tasks
             WHERE result_path IS NOT NULL
               AND status = 'done'
               AND completed_at IS NOT NULL
               AND datetime(completed_at) < datetime('now', '-{int(CLEANUP_OUTPUT_DELAY_SECONDS)} seconds')
            """
        ).fetchall()
        for row in rows:
            _safe_unlink(row["result_path"])
            conn.execute("UPDATE tasks SET result_path = NULL WHERE id = ?", (row["id"],))


async def cleaner_loop() -> None:
    logger.info("Cleaner started (interval=%ss)", CLEANUP_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_cleanup_once)
        except Exception:
            logger.exception("Cleaner iteration failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)