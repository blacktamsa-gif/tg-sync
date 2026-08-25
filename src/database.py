import sqlite3
from pathlib import Path
from typing import Iterable


DB_PATH = Path(__file__).resolve().parent.parent / "state.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_messages (
            source_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            PRIMARY KEY (source_id, message_id)
        )
        """
    )

    conn.commit()
    return conn


def is_processed(source_id: int, message_id: int) -> bool:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT 1
            FROM processed_messages
            WHERE source_id = ?
              AND message_id = ?
            LIMIT 1
            """,
            (source_id, message_id),
        ).fetchone()

        return row is not None

    finally:
        conn.close()


def mark_processed(
    messages: Iterable[tuple[int, int]],
    processed_at: str,
):
    conn = get_connection()

    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO processed_messages
            (
                source_id,
                message_id,
                processed_at
            )
            VALUES (?, ?, ?)
            """,
            [
                (source_id, message_id, processed_at)
                for source_id, message_id in messages
            ],
        )

        conn.commit()

    finally:
        conn.close()
