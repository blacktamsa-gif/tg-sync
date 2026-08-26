import sqlite3
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent / "state.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(row[1] == column_name for row in rows)


def _add_column_if_missing(
    conn,
    table_name: str,
    column_name: str,
    column_definition: str,
):
    if not _column_exists(conn, table_name, column_name):
        conn.execute(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} {column_definition}"
        )


def init_db():
    conn = get_connection()

    try:
        # --------------------------------------------------
        # 기존 DB가 없는 경우 기본 테이블 생성
        # --------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                message_id INTEGER,
                processed_at TEXT,
                UNIQUE(source_id, message_id)
            )
            """
        )

        # --------------------------------------------------
        # 기존 state.db 마이그레이션
        #
        # 예전 버전에서 source_id가 없었던 경우
        # 자동으로 컬럼 추가
        # --------------------------------------------------

        _add_column_if_missing(
            conn,
            "processed_messages",
            "source_id",
            "INTEGER",
        )

        _add_column_if_missing(
            conn,
            "processed_messages",
            "message_id",
            "INTEGER",
        )

        _add_column_if_missing(
            conn,
            "processed_messages",
            "processed_at",
            "TEXT",
        )

        # --------------------------------------------------
        # 기존 DB의 UNIQUE index가 없더라도
        # 새 구조에서는 source_id + message_id를 기준으로
        # 중복 방지
        # --------------------------------------------------

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_processed_source_message
            ON processed_messages(source_id, message_id)
            """
        )

        conn.commit()

    finally:
        conn.close()


def is_processed(
    source_id: int,
    message_id: int,
) -> bool:

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
            (
                int(source_id),
                int(message_id),
            ),
        ).fetchone()

        return row is not None

    finally:
        conn.close()


def mark_processed(
    source_id: int,
    message_id: int,
):
    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_messages
            (
                source_id,
                message_id,
                processed_at
            )
            VALUES (?, ?, datetime('now'))
            """,
            (
                int(source_id),
                int(message_id),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def mark_processed_many(
    source_id: int,
    message_ids,
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
            VALUES (?, ?, datetime('now'))
            """,
            [
                (
                    int(source_id),
                    int(message_id),
                )
                for message_id in message_ids
            ],
        )

        conn.commit()

    finally:
        conn.close()


def get_processed_count() -> int:
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_messages
            """
        ).fetchone()

        return int(row[0])

    finally:
        conn.close()


def get_processed_count_for_source(
    source_id: int,
) -> int:

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_messages
            WHERE source_id = ?
            """,
            (int(source_id),),
        ).fetchone()

        return int(row[0])

    finally:
        conn.close()


def remove_processed(
    source_id: int,
    message_id: int,
):
    conn = get_connection()

    try:
        conn.execute(
            """
            DELETE FROM processed_messages
            WHERE source_id = ?
              AND message_id = ?
            """,
            (
                int(source_id),
                int(message_id),
            ),
        )

        conn.commit()

    finally:
        conn.close()
