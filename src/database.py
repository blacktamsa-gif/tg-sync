import sqlite3
from pathlib import Path
from typing import Iterable


# ============================================================
# DATABASE PATH
# ============================================================

DB_PATH = Path(__file__).resolve().parent / "state.db"


# ============================================================
# CONNECTION
# ============================================================

def get_connection():
    """
    SQLite connection 생성.

    GitHub Actions에서 cache 복원 후 사용할 수 있도록
    WAL + busy_timeout 적용.
    """

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


# ============================================================
# SCHEMA HELPERS
# ============================================================

def _column_exists(
    conn,
    table_name: str,
    column_name: str,
) -> bool:

    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    for row in rows:
        # PRAGMA table_info:
        # 0 = cid
        # 1 = name
        if row[1] == column_name:
            return True

    return False


def _add_column_if_missing(
    conn,
    table_name: str,
    column_name: str,
    column_definition: str,
):
    """
    기존 state.db에 없는 컬럼을 자동 추가.
    """

    if not _column_exists(
        conn,
        table_name,
        column_name,
    ):

        print(
            f"[DATABASE MIGRATION] "
            f"Adding column {column_name}"
        )

        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_definition}
            """
        )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():
    """
    데이터베이스 초기화 및 기존 DB 마이그레이션.

    이전 버전 state.db가 존재하더라도 삭제하지 않고
    필요한 컬럼만 추가한다.
    """

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # 기본 테이블
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_id INTEGER,

                message_id INTEGER,

                processed_at TEXT

            )
            """
        )

        # ----------------------------------------------------
        # 기존 DB migration
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 중복 방지 index
        #
        # 같은 source의 같은 Telegram message는
        # 한 번만 처리한다.
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_processed_source_message
            ON processed_messages(
                source_id,
                message_id
            )
            """
        )

        conn.commit()

        print(
            f"[DATABASE] initialized: {DB_PATH}"
        )

    finally:
        conn.close()


# ============================================================
# PROCESSED CHECK
# ============================================================

def is_processed(
    source_id: int,
    message_id: int,
) -> bool:
    """
    특정 source의 특정 message가
    이미 처리되었는지 확인.
    """

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


# ============================================================
# MARK SINGLE MESSAGE
# ============================================================

def mark_processed(
    source_id: int,
    message_id: int,
):
    """
    영상 업로드가 성공한 뒤
    해당 Telegram message를 처리 완료로 기록.
    """

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
            VALUES
            (
                ?,
                ?,
                datetime('now')
            )
            """,
            (
                int(source_id),
                int(message_id),
            ),
        )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# MARK MULTIPLE MESSAGES
# ============================================================

def mark_processed_many(
    source_id: int,
    message_ids: Iterable[int],
):
    """
    앨범 등 여러 영상 메시지를 한 번에
    처리 완료로 기록.
    """

    message_ids = list(message_ids)

    if not message_ids:
        return

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
            VALUES
            (
                ?,
                ?,
                datetime('now')
            )
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


# ============================================================
# COUNT
# ============================================================

def count_processed() -> int:
    """
    전체 처리 완료 메시지 수.

    중요:
    현재 main.py에서 사용하는 기존 함수 이름.
    """

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


# ============================================================
# ALIAS
# ============================================================

def get_processed_count() -> int:
    """
    기존/신규 코드 호환용 alias.
    """

    return count_processed()


# ============================================================
# SOURCE-SPECIFIC COUNT
# ============================================================

def count_processed_for_source(
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
            (
                int(source_id),
            ),
        ).fetchone()

        return int(row[0])

    finally:
        conn.close()


def get_processed_count_for_source(
    source_id: int,
) -> int:
    """
    기존/신규 코드 호환용 alias.
    """

    return count_processed_for_source(source_id)


# ============================================================
# REMOVE PROCESSED
# ============================================================

def remove_processed(
    source_id: int,
    message_id: int,
):
    """
    특정 처리 기록 삭제.

    일반적인 실행에서는 사용하지 않는다.
    테스트/복구용.
    """

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


# ============================================================
# DEBUG
# ============================================================

def print_database_status():
    """
    GitHub Actions 로그 확인용.
    """

    conn = get_connection()

    try:

        print(
            "============================================================"
        )
        print("[DATABASE STATUS]")

        # 테이블 존재 확인
        tables = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'processed_messages'
            """
        ).fetchall()

        print(
            f"[DATABASE] processed_messages exists="
            f"{bool(tables)}"
        )

        if not tables:
            return

        # 컬럼 확인
        columns = conn.execute(
            """
            PRAGMA table_info(processed_messages)
            """
        ).fetchall()

        print("[DATABASE] columns:")

        for column in columns:
            print(
                f"  - {column[1]} "
                f"type={column[2]}"
            )

        # 전체 처리 수
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_messages
            """
        ).fetchone()

        print(
            f"[DATABASE] processed={row[0]}"
        )

        print(
            "============================================================"
        )

    finally:
        conn.close()
