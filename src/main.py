import os
import asyncio
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeVideo,
    MessageMediaDocument,
)

from database import (
    is_processed,
    mark_processed,
)


# ============================================================
# Configuration
# ============================================================

UTC = timezone.utc

# KST 2026-08-25 18:00
# = UTC 2026-08-25 09:00
CUTOFF_TIME = datetime(
    2026,
    8,
    25,
    9,
    0,
    0,
    tzinfo=UTC,
)

# GitHub Actions는 매시간 실행되므로
# 실행 지연 및 경계 누락을 방지하기 위해 70분을 조회한다.
LOOKBACK_MINUTES = 70


# ============================================================
# Secret helpers
# ============================================================

def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()

    if not value:
        raise RuntimeError(
            f"GitHub Actions Secret '{name}' is missing or empty."
        )

    return value


# ============================================================
# Telegram configuration
# ============================================================

try:
    API_ID = int(required_secret("API_ID"))
except ValueError:
    raise RuntimeError(
        "GitHub Actions Secret 'API_ID' must contain numbers only."
    )


API_HASH = required_secret("API_HASH")
SESSION = required_secret("SESSION")

TARGET_CHAT = int(required_secret("TARGET_CHAT"))

TOPIC_A = int(required_secret("TOPIC_A"))
TOPIC_B = int(required_secret("TOPIC_B"))


SOURCE_A = required_secret("SOURCE_A")
SOURCE_B = required_secret("SOURCE_B")
SOURCE_C = required_secret("SOURCE_C")
SOURCE_D = required_secret("SOURCE_D")


SOURCE_MAPPING = {
    SOURCE_A: TOPIC_A,
    SOURCE_B: TOPIC_A,
    SOURCE_C: TOPIC_B,
    SOURCE_D: TOPIC_B,
}


# ============================================================
# Telegram Client
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
)


# ============================================================
# Utility functions
# ============================================================

def normalize_datetime(dt: datetime) -> datetime:
    """
    Telegram datetime를 UTC aware datetime으로 변환.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC)


def calculate_since() -> datetime:
    """
    이번 실행에서 조회를 시작할 시간.

    예:
    현재 19:00 KST라면 약 17:50 KST부터 확인.

    단, 최초 기준인
    2026-08-25 18:00 KST
    이전은 절대로 처리하지 않는다.
    """

    now = datetime.now(UTC)

    lookback = now - timedelta(
        minutes=LOOKBACK_MINUTES
    )

    return max(
        lookback,
        CUTOFF_TIME,
    )


def is_video_message(message) -> bool:
    """
    메시지가 실제 동영상인지 확인.

    사진, 텍스트, 일반 문서 등은 제외한다.
    """

    if message is None:
        return False

    if not message.media:
        return False

    if not isinstance(
        message.media,
        MessageMediaDocument,
    ):
        return False

    document = message.document

    if document is None:
        return False

    for attribute in document.attributes:
        if isinstance(
            attribute,
            DocumentAttributeVideo,
        ):
            return True

    return False


def get_group_key(message):
    """
    Telegram 앨범 여부를 판단한다.

    grouped_id가 있으면 같은 앨범으로 처리한다.

    사진 + 동영상이 섞인 앨범이어도
    이후 is_video_message() 단계에서
    동영상만 남긴다.
    """

    if message.grouped_id is not None:
        return (
            "album",
            int(message.grouped_id),
        )

    return (
        "single",
        int(message.id),
    )


def group_messages(messages):
    """
    메시지를 앨범 단위로 묶는다.
    """

    groups = {}

    for message in messages:

        key = get_group_key(message)

        groups.setdefault(
            key,
            [],
        ).append(message)

    for key in groups:
        groups[key].sort(
            key=lambda message: message.id
        )

    return sorted(
        groups.values(),
        key=lambda group: group[0].id,
    )


# ============================================================
# Message collection
# ============================================================

async def collect_recent_messages(
    source,
    since: datetime,
):
    """
    Source에서 since 이후의 메시지를 가져온다.

    Telegram Forum Topic에 관계없이
    source 전체 메시지를 검색한다.
    """

    entity = await client.get_entity(source)

    print(
        f"[SOURCE ENTITY] "
        f"name={getattr(entity, 'title', None)!r} "
        f"id={getattr(entity, 'id', None)}"
    )

    collected = []

    now = datetime.now(UTC)

    async for message in client.iter_messages(
        entity,
        reverse=True,
    ):

        if not message.date:
            continue

        message_time = normalize_datetime(
            message.date
        )

        # 최초 기준보다 이전이면 절대 처리하지 않는다.
        if message_time < CUTOFF_TIME:
            continue

        # 이번 실행의 조회 범위 이전이면 종료.
        if message_time < since:
            break

        # 미래 메시지는 무시.
        if message_time > now:
            continue

        collected.append(message)

    return collected


# ============================================================
# Upload
# ============================================================

async def send_video_group(
    messages,
    target_chat,
    topic_id,
):
    """
    하나의 메시지 또는 앨범에서
    동영상만 추출하여 Target Topic으로 전송.
    """

    # --------------------------------------------------------
    # 동영상만 남긴다.
    # --------------------------------------------------------

    video_messages = [
        message
        for message in messages
        if is_video_message(message)
    ]

    print(
        f"[GROUP] "
        f"total_messages={len(messages)} "
        f"video_messages={len(video_messages)}"
    )

    if not video_messages:
        print(
            "[SKIP] "
            "No video in this message/group."
        )

        return

    # --------------------------------------------------------
    # 이미 처리한 동영상 제거
    # --------------------------------------------------------

    new_video_messages = []

    for message in video_messages:

        source_id = int(message.chat_id)
        message_id = int(message.id)

        if is_processed(
            source_id,
            message_id,
        ):
            print(
                f"[DUPLICATE] "
                f"source={source_id} "
                f"message={message_id}"
            )

            continue

        new_video_messages.append(
            message
        )

    if not new_video_messages:

        print(
            "[SKIP] "
            "All videos were already processed."
        )

        return

    # --------------------------------------------------------
    # 로그
    # --------------------------------------------------------

    message_ids = [
        int(message.id)
        for message in new_video_messages
    ]

    print(
        f"[UPLOAD] "
        f"target={target_chat} "
        f"topic={topic_id} "
        f"message_ids={message_ids}"
    )

    # --------------------------------------------------------
    # 실제 Telegram 업로드
    # --------------------------------------------------------

    media = [
        message.media
        for message in new_video_messages
    ]

    try:

        await client.send_file(
            entity=target_chat,
            file=media,
            caption=None,

            # Forum Topic의 root message ID
            reply_to=topic_id,
        )

    except Exception as exc:

        print(
            f"[UPLOAD ERROR] "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        # 업로드 실패 시 processed 기록을 하지 않는다.
        # 다음 실행에서 다시 시도할 수 있게 한다.
        raise

    # --------------------------------------------------------
    # 업로드 성공
    # --------------------------------------------------------

    print(
        f"[UPLOAD SUCCESS] "
        f"topic={topic_id} "
        f"videos={len(new_video_messages)}"
    )

    processed_at = datetime.now(
        UTC
    ).isoformat()

    mark_processed(
        [
            (
                int(message.chat_id),
                int(message.id),
            )
            for message in new_video_messages
        ],
        processed_at,
    )

    print(
        f"[DATABASE] "
        f"marked={len(new_video_messages)}"
    )


# ============================================================
# Source processing
# ============================================================

async def process_source(
    source,
    target_chat,
    topic_id,
    since,
):
    """
    하나의 Source 처리.
    """

    print()
    print("=" * 70)
    print(
        f"[PROCESS SOURCE] "
        f"{source}"
    )
    print(
        f"[DESTINATION TOPIC] "
        f"{topic_id}"
    )
    print(
        f"[SINCE] "
        f"{since.isoformat()}"
    )
    print("=" * 70)

    try:

        messages = await collect_recent_messages(
            source,
            since,
        )

    except Exception as exc:

        print(
            f"[SOURCE ERROR] "
            f"source={source} "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        raise

    print(
        f"[MESSAGES FOUND] "
        f"{len(messages)}"
    )

    if not messages:

        print(
            "[SKIP SOURCE] "
            "No messages in time range."
        )

        return

    groups = group_messages(
        messages
    )

    print(
        f"[GROUPS FOUND] "
        f"{len(groups)}"
    )

    for index, group in enumerate(
        groups,
        start=1,
    ):

        print()
        print(
            f"[GROUP {index}/{len(groups)}]"
        )

        try:

            await send_video_group(
                group,
                target_chat,
                topic_id,
            )

        except Exception as exc:

            print(
                f"[GROUP ERROR] "
                f"type={type(exc).__name__} "
                f"message={exc}"
            )

            raise


# ============================================================
# Main
# ============================================================

async def main():

    since = calculate_since()

    now = datetime.now(UTC)

    print()
    print("=" * 70)
    print("Telegram Scheduled Video Processor")
    print("=" * 70)

    print(
        f"[NOW UTC] "
        f"{now.isoformat()}"
    )

    print(
        f"[CUTOFF UTC] "
        f"{CUTOFF_TIME.isoformat()}"
    )

    print(
        f"[CUTOFF KST] "
        f"2026-08-25 18:00:00+09:00"
    )

    print(
        f"[LOOKBACK] "
        f"{LOOKBACK_MINUTES} minutes"
    )

    print(
        f"[SINCE UTC] "
        f"{since.isoformat()}"
    )

    print(
        f"[TARGET CHAT] "
        f"{TARGET_CHAT}"
    )

    print(
        f"[TOPIC A] "
        f"{TOPIC_A}"
    )

    print(
        f"[TOPIC B] "
        f"{TOPIC_B}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # Telegram 로그인
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Connecting..."
    )

    await client.start()

    me = await client.get_me()

    if me is None:
        raise RuntimeError(
            "Telegram authentication failed."
        )

    print(
        f"[TELEGRAM] Logged in as "
        f"{getattr(me, 'first_name', '')} "
        f"(id={me.id})"
    )

    # --------------------------------------------------------
    # Source 처리
    # --------------------------------------------------------

    total_sources = len(
        SOURCE_MAPPING
    )

    for index, (
        source,
        topic_id,
    ) in enumerate(
        SOURCE_MAPPING.items(),
        start=1,
    ):

        print()
        print(
            f"[SOURCE {index}/{total_sources}]"
        )

        try:

            await process_source(
                source,
                TARGET_CHAT,
                topic_id,
                since,
            )

        except Exception as exc:

            print(
                f"[SOURCE FAILED] "
                f"source={source} "
                f"type={type(exc).__name__} "
                f"message={exc}"
            )

            # 한 Source가 실패해도
            # 다른 Source는 계속 처리한다.
            continue

    # --------------------------------------------------------
    # 종료
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("JOB FINISHED")
    print("=" * 70)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except Exception as exc:

        print()
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)

        print(
            f"type={type(exc).__name__}"
        )

        print(
            f"message={exc}"
        )

        raise
