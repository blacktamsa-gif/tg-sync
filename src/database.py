import os
import sqlite3
from typing import Iterable, Tuple


# ============================================================
# Database location
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DB_PATH = os.path.join(
    BASE_DIR,
    "state.db",
)


# ============================================================
# Connection
# ============================================================

def get_connection():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.execute(
        """
        PRAGMA journal_mode=WAL
        """
    )

    conn.execute(
        """
        PRAGMA busy_timeout=30000
        """
    )

    return conn


# ============================================================
# Initialize
# ============================================================

def init_db():
    """
    처리 완료된 Telegram 메시지 ID를 저장한다.
    """

    os.makedirs(
        BASE_DIR,
        exist_ok=True,
    )

    with get_connection() as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                source_chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                processed_at TEXT NOT NULL,
                PRIMARY KEY (
                    source_chat_id,
                    message_id
                )
            )
            """
        )

        conn.commit()


# ============================================================
# Check processed
# ============================================================

def is_processed(
    source_chat_id: int,
    message_id: int,
) -> bool:

    init_db()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT 1
            FROM processed_messages
            WHERE source_chat_id = ?
              AND message_id = ?
            LIMIT 1
            """,
            (
                int(source_chat_id),
                int(message_id),
            ),
        ).fetchone()

    return row is not None


# ============================================================
# Mark processed
# ============================================================

def mark_processed(
    messages: Iterable[Tuple[int, int]],
    processed_at: str,
):
    """
    업로드가 성공한 동영상만 기록한다.
    """

    init_db()

    rows = [
        (
            int(source_chat_id),
            int(message_id),
            processed_at,
        )
        for source_chat_id, message_id
        in messages
    ]

    if not rows:
        return

    with get_connection() as conn:

        conn.executemany(
            """
            INSERT OR IGNORE INTO processed_messages
            (
                source_chat_id,
                message_id,
                processed_at
            )
            VALUES (?, ?, ?)
            """,
            rows,
        )

        conn.commit()


# ============================================================
# Statistics
# ============================================================

def count_processed() -> int:

    init_db()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_messages
            """
        ).fetchone()

    return int(
        row[0]
    )
