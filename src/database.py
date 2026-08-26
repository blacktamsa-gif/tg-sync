import sqlite3
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent / "state.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_messages (
            source_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
            WHERE source_id = ? AND message_id = ?
            LIMIT 1
            """,
            (source_id, message_id),
        ).fetchone()

        return row is not None

    finally:
        conn.close()


def mark_processed(source_id: int, message_id: int):
    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_messages
            (
                source_id,
                message_id
            )
            VALUES (?, ?)
            """,
            (source_id, message_id),
        )

        conn.commit()

    finally:
        conn.close()


def mark_processed_many(source_id: int, message_ids):
    conn = get_connection()

    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO processed_messages
            (
                source_id,
                message_id
            )
            VALUES (?, ?)
            """,
            [
                (source_id, int(message_id))
                for message_id in message_ids
            ],
        )

        conn.commit()

    finally:
        conn.close()


def count_processed() -> int:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_messages
            """
        ).fetchone()

        return int(row[0] or 0)

    finally:
        conn.close()


def get_max_processed_message_id(source_id: int) -> Optional[int]:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT MAX(message_id)
            FROM processed_messages
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()

        if row is None or row[0] is None:
            return None

        return int(row[0])

    finally:
        conn.close()
