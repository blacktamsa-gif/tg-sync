import os
import asyncio
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, utils
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
# Time configuration
# ============================================================

UTC = timezone.utc

# 최초 처리 기준
#
# KST 2026-08-25 18:00:00
# =
# UTC 2026-08-25 09:00:00
#
# 이 시각보다 이전의 메시지는 절대로 처리하지 않는다.
CUTOFF_TIME = datetime(
    2026,
    8,
    25,
    9,
    0,
    0,
    tzinfo=UTC,
)

# GitHub Actions가 매시간 실행되므로
# 실행 지연 및 시간 경계에서 메시지가 빠지는 것을 방지하기 위해
# 직전 70분을 조회한다.
LOOKBACK_MINUTES = 70


# ============================================================
# Secret helper
# ============================================================

def required_secret(name: str) -> str:
    """
    GitHub Actions Secret을 가져온다.

    Secret이 없거나 빈 값이면
    정확한 Secret 이름을 표시하고 종료한다.

    실제 Secret 값은 로그에 출력하지 않는다.
    """

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
    API_ID = int(
        required_secret("API_ID")
    )

except ValueError:
    raise RuntimeError(
        "GitHub Actions Secret 'API_ID' "
        "must contain numbers only."
    )


API_HASH = required_secret("API_HASH")
SESSION = required_secret("SESSION")

TARGET_CHAT = int(
    required_secret("TARGET_CHAT")
)

TOPIC_A = int(
    required_secret("TOPIC_A")
)

TOPIC_B = int(
    required_secret("TOPIC_B")
)


SOURCE_A = required_secret("SOURCE_A")
SOURCE_B = required_secret("SOURCE_B")
SOURCE_C = required_secret("SOURCE_C")
SOURCE_D = required_secret("SOURCE_D")


# ============================================================
# Source → destination topic mapping
# ============================================================

SOURCE_MAPPING = {
    SOURCE_A: TOPIC_A,
    SOURCE_B: TOPIC_A,
    SOURCE_C: TOPIC_B,
    SOURCE_D: TOPIC_B,
}


# ============================================================
# Telegram client
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
)


# ============================================================
# Entity cache
# ============================================================

# 한 번 조회한 Telegram Dialog/Entity를
# 같은 실행 중에는 다시 조회하지 않는다.
DIALOG_ENTITIES = None


async def load_dialog_entities():
    """
    현재 로그인한 계정의 Telegram 대화 목록을 한 번만 가져온다.

    private chat / group / supergroup / channel 등을
    모두 포함한다.

    반환값:
        {
            peer_id: entity,
            raw_id: entity,
            username: entity
        }
    """

    global DIALOG_ENTITIES

    if DIALOG_ENTITIES is not None:
        return DIALOG_ENTITIES

    print()
    print("[DIALOGS] Loading Telegram dialogs...")

    dialogs = await client.get_dialogs()

    by_peer_id = {}
    by_raw_id = {}
    by_username = {}

    for dialog in dialogs:

        entity = dialog.entity

        # ----------------------------------------------------
        # Peer ID
        # ----------------------------------------------------

        try:
            peer_id = utils.get_peer_id(
                entity
            )

            by_peer_id[
                str(peer_id)
            ] = entity

        except Exception:
            pass

        # ----------------------------------------------------
        # Raw ID
        # ----------------------------------------------------

        try:
            raw_id = getattr(
                entity,
                "id",
                None,
            )

            if raw_id is not None:
                by_raw_id[
                    str(raw_id)
                ] = entity

        except Exception:
            pass

        # ----------------------------------------------------
        # Username
        # ----------------------------------------------------

        try:
            username = getattr(
                entity,
                "username",
                None,
            )

            if username:
                by_username[
                    username.lower()
                ] = entity

        except Exception:
            pass

    DIALOG_ENTITIES = {
        "peer_id": by_peer_id,
        "raw_id": by_raw_id,
        "username": by_username,
    }

    print(
        f"[DIALOGS] Loaded {len(dialogs)} dialogs."
    )

    print(
        f"[DIALOGS] "
        f"peer_ids={len(by_peer_id)} "
        f"raw_ids={len(by_raw_id)} "
        f"usernames={len(by_username)}"
    )

    return DIALOG_ENTITIES


# ============================================================
# Resolve Telegram source
# ============================================================

async def resolve_source_entity(source):
    """
    Source를 실제 Telethon Entity로 변환한다.

    우선 현재 로그인한 계정의 Dialog 목록에서 찾는다.

    지원:
        - -100xxxxxxxxxx 형태의 Peer ID
        - Raw ID
        - @username
        - username

    Dialog 목록에서 찾지 못하면
    마지막으로 client.get_entity()를 시도한다.
    """

    source = str(
        source
    ).strip()

    print(
        f"[RESOLVE] Trying source={source}"
    )

    entities = await load_dialog_entities()

    # --------------------------------------------------------
    # 1. Peer ID
    # --------------------------------------------------------

    entity = entities["peer_id"].get(
        source
    )

    if entity is not None:

        print(
            f"[RESOLVE SUCCESS] "
            f"Matched Peer ID {source}"
        )

        return entity

    # --------------------------------------------------------
    # 2. Raw ID
    # --------------------------------------------------------

    entity = entities["raw_id"].get(
        source
    )

    if entity is not None:

        print(
            f"[RESOLVE SUCCESS] "
            f"Matched Raw ID {source}"
        )

        return entity

    # --------------------------------------------------------
    # 3. Username
    # --------------------------------------------------------

    username = source.lstrip("@").lower()

    entity = entities["username"].get(
        username
    )

    if entity is not None:

        print(
            f"[RESOLVE SUCCESS] "
            f"Matched username @{username}"
        )

        return entity

    # --------------------------------------------------------
    # 4. get_entity() fallback
    # --------------------------------------------------------

    try:

        entity = await client.get_entity(
            source
        )

        print(
            f"[RESOLVE SUCCESS] "
            f"client.get_entity({source})"
        )

        return entity

    except Exception as exc:

        print(
            f"[RESOLVE FAILED] "
            f"source={source} "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        raise ValueError(
            f"Cannot resolve Telegram source: {source}. "
            f"The logged-in Telegram account may not have "
            f"access to this group/channel, or the supplied "
            f"ID/username is incorrect."
        ) from exc


# ============================================================
# Time utilities
# ============================================================

def normalize_datetime(
    dt: datetime,
) -> datetime:
    """
    Telegram datetime을 UTC aware datetime으로 변환한다.
    """

    if dt.tzinfo is None:

        return dt.replace(
            tzinfo=UTC
        )

    return dt.astimezone(
        UTC
    )


def calculate_since() -> datetime:
    """
    이번 실행에서 검색할 시작 시각.

    현재 시각에서 70분을 빼되,
    최초 기준 시각인 2026-08-25 18:00 KST보다
    이전으로 내려가지 않는다.
    """

    now = datetime.now(
        UTC
    )

    lookback = (
        now
        - timedelta(
            minutes=LOOKBACK_MINUTES
        )
    )

    return max(
        lookback,
        CUTOFF_TIME,
    )


# ============================================================
# Video detection
# ============================================================

def is_video_message(
    message,
) -> bool:
    """
    메시지가 동영상인지 확인한다.

    포함:
        - Telegram video
        - video document

    제외:
        - text
        - photo
        - 일반 document
        - sticker
        - 기타 media
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


# ============================================================
# Album grouping
# ============================================================

def get_group_key(
    message,
):
    """
    Telegram 앨범 그룹을 판단한다.

    grouped_id가 동일한 메시지는
    하나의 앨범으로 묶는다.

    사진 + 동영상이 섞인 앨범도
    같은 그룹으로 먼저 묶은 뒤,
    upload 단계에서 동영상만 남긴다.
    """

    if message.grouped_id is not None:

        return (
            "album",
            int(
                message.grouped_id
            ),
        )

    return (
        "single",
        int(
            message.id
        ),
    )


def group_messages(
    messages,
):
    """
    메시지를 Telegram 앨범 단위로 그룹화한다.

    예:

        사진
        동영상
        동영상
        사진

    같은 grouped_id라면:

        [사진, 동영상, 동영상, 사진]

    하나의 그룹으로 만든다.

    이후 업로드 단계에서:

        [동영상, 동영상]

    만 추출한다.
    """

    groups = {}

    for message in messages:

        key = get_group_key(
            message
        )

        groups.setdefault(
            key,
            [],
        ).append(
            message
        )

    # 각 앨범 내부를 메시지 ID 순서로 정렬
    for key in groups:

        groups[key].sort(
            key=lambda message: message.id
        )

    # 앨범/개별 메시지를 메시지 ID 순서로 정렬
    return sorted(
        groups.values(),
        key=lambda group: group[0].id,
    )


# ============================================================
# Collect recent messages
# ============================================================

async def collect_recent_messages(
    source,
    since: datetime,
):
    """
    Source 전체에서 since 이후의 메시지를 검색한다.

    중요:
        Telegram Forum Topic 여부와 관계없이
        해당 그룹/채널의 전체 메시지를 검색한다.

    Forum Topic의 특정 topic ID를 필터로 사용하지 않는다.
    """

    entity = await resolve_source_entity(
        source
    )

    entity_name = getattr(
        entity,
        "title",
        None,
    )

    entity_id = getattr(
        entity,
        "id",
        None,
    )

    print(
        f"[SOURCE ENTITY] "
        f"name={entity_name!r} "
        f"id={entity_id}"
    )

    collected = []

    now = datetime.now(
        UTC
    )

    # --------------------------------------------------------
    # 최신 메시지 → 오래된 메시지 순서
    #
    # reverse=True를 사용하지 않는다.
    # 기본 iter_messages()는 최신 메시지부터 내려간다.
    # --------------------------------------------------------

    async for message in client.iter_messages(
        entity,
    ):

        if not message.date:
            continue

        message_time = normalize_datetime(
            message.date
        )

        # ----------------------------------------------------
        # 너무 오래된 메시지
        #
        # 최신 → 과거 순으로 읽기 때문에
        # since보다 오래된 순간 종료한다.
        # ----------------------------------------------------

        if message_time < since:

            break

        # ----------------------------------------------------
        # 최초 cutoff 이전은 절대 처리하지 않는다.
        # ----------------------------------------------------

        if message_time < CUTOFF_TIME:

            continue

        # ----------------------------------------------------
        # 미래 메시지 무시
        # ----------------------------------------------------

        if message_time > now:

            continue

        collected.append(
            message
        )

    return collected


# ============================================================
# Upload video group
# ============================================================

async def send_video_group(
    messages,
    target_chat,
    topic_id,
):
    """
    하나의 개별 메시지 또는 앨범에서
    동영상만 추출하여 대상 Forum Topic으로 업로드한다.

    규칙:

        text       → 제외
        photo      → 제외
        video      → 업로드
        album      → video만 업로드

    앨범에 동영상이 여러 개 있으면
    하나의 Telegram album으로 보낸다.
    """

    # --------------------------------------------------------
    # 1. 동영상만 추출
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
    # 2. 이미 처리된 동영상 제거
    # --------------------------------------------------------

    new_video_messages = []

    for message in video_messages:

        source_id = int(
            message.chat_id
        )

        message_id = int(
            message.id
        )

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
    # 3. 업로드 로그
    # --------------------------------------------------------

    message_ids = [
        int(
            message.id
        )
        for message in new_video_messages
    ]

    print(
        f"[UPLOAD] "
        f"target={target_chat} "
        f"topic={topic_id} "
        f"message_ids={message_ids}"
    )

    # --------------------------------------------------------
    # 4. Media 추출
    #
    # caption을 전달하지 않기 때문에
    # 원본 동영상의 설명/텍스트는 복사하지 않는다.
    #
    # 사진은 이미 위에서 제거되었다.
    # --------------------------------------------------------

    media = [
        message.media
        for message in new_video_messages
    ]

    try:

        # ----------------------------------------------------
        # 여러 동영상:
        # Telegram album으로 전송
        #
        # 하나의 동영상:
        # 단일 파일 전송
        # ----------------------------------------------------

        if len(media) == 1:

            await client.send_file(
                entity=target_chat,
                file=media[0],
                caption=None,
                reply_to=topic_id,
            )

        else:

            await client.send_file(
                entity=target_chat,
                file=media,
                caption=None,
                reply_to=topic_id,
            )

    except Exception as exc:

        print(
            f"[UPLOAD ERROR] "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        # 업로드 실패 시 database에 기록하지 않는다.
        # 다음 실행에서 다시 시도할 수 있다.

        raise

    # --------------------------------------------------------
    # 5. 업로드 성공
    # --------------------------------------------------------

    print(
        f"[UPLOAD SUCCESS] "
        f"topic={topic_id} "
        f"videos={len(new_video_messages)}"
    )

    # --------------------------------------------------------
    # 6. DB에 처리 완료 기록
    #
    # 반드시 업로드 성공 후에 기록한다.
    # --------------------------------------------------------

    processed_at = datetime.now(
        UTC
    ).isoformat()

    mark_processed(
        [
            (
                int(
                    message.chat_id
                ),
                int(
                    message.id
                ),
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
# Process one source
# ============================================================

async def process_source(
    source,
    target_chat,
    topic_id,
    since,
):
    """
    하나의 Source를 처리한다.
    """

    print()
    print(
        "=" * 70
    )

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

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # 메시지 검색
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 앨범 그룹화
    # --------------------------------------------------------

    groups = group_messages(
        messages
    )

    print(
        f"[GROUPS FOUND] "
        f"{len(groups)}"
    )

    # --------------------------------------------------------
    # 그룹별 처리
    # --------------------------------------------------------

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

            # 한 앨범 실패 시 해당 Source의 다음 그룹도
            # 계속 처리한다.
            #
            # 단, 실패한 메시지는 DB에 기록되지 않았으므로
            # 다음 실행에서 재시도된다.
            continue


# ============================================================
# Main
# ============================================================

async def main():

    # --------------------------------------------------------
    # 실행 시간 계산
    # --------------------------------------------------------

    now = datetime.now(
        UTC
    )

    since = calculate_since()

    print()
    print(
        "=" * 70
    )

    print(
        "Telegram Scheduled Video Processor"
    )

    print(
        "=" * 70
    )

    print(
        f"[NOW UTC] "
        f"{now.isoformat()}"
    )

    print(
        f"[CUTOFF UTC] "
        f"{CUTOFF_TIME.isoformat()}"
    )

    print(
        "[CUTOFF KST] "
        "2026-08-25 18:00:00+09:00"
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

    print(
        "=" * 70
    )

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

            # Source 하나가 실패해도
            # 나머지 Source는 계속 처리한다.
            continue

    # --------------------------------------------------------
    # 종료
    # --------------------------------------------------------

    print()
    print(
        "=" * 70
    )

    print(
        "JOB FINISHED"
    )

    print(
        "=" * 70
    )


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
        print(
            "=" * 70
        )

        print(
            "FATAL ERROR"
        )

        print(
            "=" * 70
        )

        print(
            f"type={type(exc).__name__}"
        )

        print(
            f"message={exc}"
        )

        raise
