from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                picture_hash    TEXT    NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'pending',
                input_path      TEXT    NOT NULL,
                result_path     TEXT,
                error_message   TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                started_at      TEXT,
                completed_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status_created
                ON tasks(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_tasks_completed
                ON tasks(completed_at)
                WHERE completed_at IS NOT NULL;
            """
        )