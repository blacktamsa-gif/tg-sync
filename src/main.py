import os
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo

from database import (
    init_db,
    is_processed,
    mark_processed,
    count_processed,
)


# ============================================================
# VERSION
# ============================================================

PROCESSOR_VERSION = "2026-08-26-CLEAN-UPLOAD-01"


# ============================================================
# TIME
# ============================================================

UTC = timezone.utc

# KST 2026-08-25 18:00:00
# UTC 2026-08-25 09:00:00
CUTOFF_TIME = datetime(
    2026,
    8,
    25,
    9,
    0,
    0,
    tzinfo=UTC,
)

LOOKBACK_MINUTES = 70


# ============================================================
# ENVIRONMENT
# ============================================================

def get_required(name: str) -> str:

    value = os.environ.get(
        name,
        "",
    ).strip()

    if not value:

        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value


try:

    API_ID = int(
        get_required("API_ID")
    )

except ValueError:

    raise RuntimeError(
        "API_ID must be an integer."
    )


API_HASH = get_required(
    "API_HASH"
)

SESSION = get_required(
    "SESSION"
)

TARGET_CHAT = int(
    get_required("TARGET_CHAT")
)

TOPIC_A = int(
    get_required("TOPIC_A")
)

TOPIC_B = int(
    get_required("TOPIC_B")
)


SOURCE_A = get_required(
    "SOURCE_A"
)

SOURCE_B = get_required(
    "SOURCE_B"
)

SOURCE_C = get_required(
    "SOURCE_C"
)

SOURCE_D = get_required(
    "SOURCE_D"
)


# ============================================================
# SOURCE → TOPIC
# ============================================================

SOURCE_MAPPING = [
    (
        SOURCE_A,
        TOPIC_A,
    ),
    (
        SOURCE_B,
        TOPIC_A,
    ),
    (
        SOURCE_C,
        TOPIC_B,
    ),
    (
        SOURCE_D,
        TOPIC_B,
    ),
]


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
)


# ============================================================
# ENTITY CACHE
# ============================================================

ENTITY_CACHE = {}


async def resolve_source(source):

    source = str(
        source
    ).strip()

    if source in ENTITY_CACHE:

        return ENTITY_CACHE[source]

    print(
        f"[RESOLVE] source={source}"
    )

    # --------------------------------------------------------
    # Load dialogs
    # --------------------------------------------------------

    print(
        "[DIALOGS] Loading Telegram dialogs..."
    )

    dialogs = await client.get_dialogs()

    print(
        f"[DIALOGS] Loaded {len(dialogs)} dialogs."
    )

    # --------------------------------------------------------
    # Search exact peer ID
    # --------------------------------------------------------

    for dialog in dialogs:

        entity = dialog.entity

        try:

            peer_id = utils.get_peer_id(
                entity
            )

            if str(peer_id) == source:

                ENTITY_CACHE[source] = entity

                print(
                    f"[RESOLVE SUCCESS] "
                    f"Matched Peer ID {source}"
                )

                return entity

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

                if str(raw_id) == source:

                    ENTITY_CACHE[source] = entity

                    print(
                        f"[RESOLVE SUCCESS] "
                        f"Matched Raw ID {source}"
                    )

                    return entity

        except Exception:
            pass

        # ----------------------------------------------------
        # Username
        # ----------------------------------------------------

        username = getattr(
            entity,
            "username",
            None,
        )

        if username:

            normalized = (
                username
                .lstrip("@")
                .lower()
            )

            if normalized == source.lstrip(
                "@"
            ).lower():

                ENTITY_CACHE[source] = entity

                print(
                    f"[RESOLVE SUCCESS] "
                    f"Matched username @{normalized}"
                )

                return entity

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    try:

        entity = await client.get_entity(
            source
        )

        ENTITY_CACHE[source] = entity

        print(
            "[RESOLVE SUCCESS] "
            f"get_entity({source})"
        )

        return entity

    except Exception as exc:

        print(
            "[RESOLVE FAILED] "
            f"source={source} "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        raise


# ============================================================
# DATETIME
# ============================================================

def utc_datetime(value):

    if value is None:

        return None

    if value.tzinfo is None:

        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


# ============================================================
# VIDEO DETECTION
# ============================================================

def is_video(message) -> bool:

    if message is None:

        return False

    document = getattr(
        message,
        "document",
        None,
    )

    if document is None:

        return False

    # --------------------------------------------------------
    # 1. Telegram video attribute
    # --------------------------------------------------------

    for attribute in getattr(
        document,
        "attributes",
        [],
    ):

        if isinstance(
            attribute,
            DocumentAttributeVideo,
        ):

            return True

    # --------------------------------------------------------
    # 2. MIME type
    # --------------------------------------------------------

    mime_type = getattr(
        document,
        "mime_type",
        None,
    )

    if mime_type:

        if mime_type.lower().startswith(
            "video/"
        ):

            return True

    # --------------------------------------------------------
    # 3. Filename extension
    # --------------------------------------------------------

    filename = getattr(
        message,
        "file",
        None,
    )

    if filename:

        name = getattr(
            filename,
            "name",
            None,
        )

        if name:

            lower = name.lower()

            video_extensions = (
                ".mp4",
                ".mov",
                ".mkv",
                ".webm",
                ".avi",
                ".m4v",
                ".mpeg",
                ".mpg",
                ".3gp",
            )

            if lower.endswith(
                video_extensions
            ):

                return True

    return False


# ============================================================
# FETCH RECENT MESSAGES
# ============================================================

async def fetch_recent_messages(
    entity,
    since,
):

    result = []

    now = datetime.now(
        UTC
    )

    async for message in client.iter_messages(
        entity
    ):

        message_time = utc_datetime(
            message.date
        )

        if message_time is None:

            continue

        # 너무 미래인 메시지는 무시
        if message_time > now:

            continue

        # 최초 cutoff 이전이면 종료
        if message_time < CUTOFF_TIME:

            break

        # 현재 실행의 lookback 이전이면 종료
        if message_time < since:

            break

        result.append(
            message
        )

    return result


# ============================================================
# ALBUM GROUPING
# ============================================================

def make_groups(messages):

    groups = {}

    for message in messages:

        grouped_id = getattr(
            message,
            "grouped_id",
            None,
        )

        if grouped_id:

            key = (
                "album",
                int(grouped_id),
            )

        else:

            key = (
                "single",
                int(message.id),
            )

        if key not in groups:

            groups[key] = []

        groups[key].append(
            message
        )

    # 각 앨범 내부 message ID 순서
    for group in groups.values():

        group.sort(
            key=lambda m: m.id
        )

    # 최신순/시간순과 관계없이
    # message ID 기준으로 안정적으로 정렬
    result = list(
        groups.values()
    )

    result.sort(
        key=lambda group: group[0].id
    )

    return result


# ============================================================
# DOWNLOAD
# ============================================================

async def download_video(
    message,
    temp_dir,
):

    source_id = int(
        message.chat_id
    )

    message_id = int(
        message.id
    )

    print(
        f"[DOWNLOAD START] "
        f"source={source_id} "
        f"message={message_id}"
    )

    extension = ".mp4"

    # Telegram 파일명에서 확장자 추출
    try:

        file_obj = getattr(
            message,
            "file",
            None,
        )

        file_name = getattr(
            file_obj,
            "name",
            None,
        )

        if file_name:

            _, ext = os.path.splitext(
                file_name
            )

            if ext:

                extension = ext

    except Exception:
        pass

    filename = (
        f"tg_{source_id}_"
        f"{message_id}"
        f"{extension}"
    )

    path = os.path.join(
        temp_dir,
        filename,
    )

    try:

        downloaded = await client.download_media(
            message,
            file=path,
        )

    except Exception as exc:

        print(
            f"[DOWNLOAD FAILED] "
            f"source={source_id} "
            f"message={message_id} "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        raise

    if not downloaded:

        raise RuntimeError(
            "download_media returned None."
        )

    if not os.path.isfile(
        downloaded
    ):

        raise RuntimeError(
            f"Downloaded file missing: "
            f"{downloaded}"
        )

    size = os.path.getsize(
        downloaded
    )

    print(
        f"[DOWNLOAD SUCCESS] "
        f"message={message_id} "
        f"size={size:,} bytes"
    )

    return downloaded


# ============================================================
# UPLOAD
# ============================================================

async def upload_videos(
    messages,
    topic_id,
):

    # --------------------------------------------------------
    # 여기서 '현재 그룹'에 포함된 메시지만 검사한다.
    # --------------------------------------------------------

    video_messages = []

    for message in messages:

        if is_video(message):

            video_messages.append(
                message
            )

    print(
        f"[VIDEO CHECK] "
        f"total_messages={len(messages)} "
        f"video_messages={len(video_messages)}"
    )

    # --------------------------------------------------------
    # 사진만 있는 앨범
    # --------------------------------------------------------

    if not video_messages:

        print(
            "[SKIP] No video in this group."
        )

        return 0

    # --------------------------------------------------------
    # DB 중복 검사
    # --------------------------------------------------------

    new_videos = []

    for message in video_messages:

        source_id = int(
            message.chat_id
        )

        message_id = int(
            message.id
        )

        processed = is_processed(
            source_id,
            message_id,
        )

        print(
            f"[CHECK DB] "
            f"message={message_id} "
            f"processed={processed}"
        )

        if processed:

            print(
                f"[SKIP DUPLICATE] "
                f"message={message_id}"
            )

            continue

        new_videos.append(
            message
        )

    if not new_videos:

        print(
            "[SKIP] "
            "All videos already processed."
        )

        return 0

    print(
        f"[NEW VIDEOS] "
        f"{len(new_videos)}"
    )

    # --------------------------------------------------------
    # Temporary directory
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="telegram_video_"
    ) as temp_dir:

        files = []

        # ====================================================
        # DOWNLOAD ALL VIDEOS
        # ====================================================

        for message in new_videos:

            path = await download_video(
                message,
                temp_dir,
            )

            files.append(
                path
            )

        # ====================================================
        # UPLOAD
        # ====================================================

        print(
            "=" * 60
        )

        print(
            f"[UPLOAD START] "
            f"files={len(files)} "
            f"target={TARGET_CHAT} "
            f"topic={topic_id}"
        )

        print(
            "[UPLOAD MODE] "
            "caption=None"
        )

        print(
            "[UPLOAD MODE] "
            "reply_to=topic"
        )

        # ----------------------------------------------------
        # 핵심:
        #
        # caption=None
        # → 설명/텍스트 전달 안 함
        #
        # reply_to=topic_id
        # → 해당 포럼 토픽으로 전송
        #
        # 파일 리스트
        # → Telegram album
        # ----------------------------------------------------

        try:

            if len(files) == 1:

                await client.send_file(
                    TARGET_CHAT,
                    files[0],
                    caption=None,
                    force_document=False,
                    reply_to=int(
                        topic_id
                    ),
                )

            else:

                # Telegram album은 한 번에 최대 10개
                # 따라서 10개 단위로 분할한다.

                for start in range(
                    0,
                    len(files),
                    10,
                ):

                    batch = files[
                        start:start + 10
                    ]

                    print(
                        f"[UPLOAD ALBUM] "
                        f"{start + 1}-"
                        f"{start + len(batch)}"
                    )

                    await client.send_file(
                        TARGET_CHAT,
                        batch,
                        caption=None,
                        force_document=False,
                        reply_to=int(
                            topic_id
                        ),
                    )

        except Exception as exc:

            print(
                "[UPLOAD FAILED]"
            )

            print(
                f"type={type(exc).__name__}"
            )

            print(
                f"message={exc}"
            )

            # ------------------------------------------------
            # 중요:
            #
            # 업로드 실패 시 DB 기록하지 않는다.
            # 다음 실행에서 재시도한다.
            # ------------------------------------------------

            raise

        # ====================================================
        # UPLOAD SUCCESS
        # ====================================================

        print(
            f"[UPLOAD SUCCESS] "
            f"videos={len(files)} "
            f"topic={topic_id}"
        )

        # ====================================================
        # DB MARK
        # ====================================================

        processed_at = datetime.now(
            UTC
        ).isoformat()

        records = []

        for message in new_videos:

            records.append(
                (
                    int(
                        message.chat_id
                    ),
                    int(
                        message.id
                    ),
                )
            )

        mark_processed(
            records,
            processed_at,
        )

        print(
            f"[DATABASE] "
            f"marked={len(records)}"
        )

        print(
            f"[DATABASE] "
            f"total_processed={count_processed()}"
        )

        return len(records)


# ============================================================
# PROCESS SOURCE
# ============================================================

async def process_source(
    source,
    topic_id,
    since,
):

    print()
    print(
        "=" * 70
    )

    print(
        f"[PROCESS SOURCE] {source}"
    )

    print(
        f"[DESTINATION TOPIC] {topic_id}"
    )

    print(
        f"[SINCE] {since.isoformat()}"
    )

    print(
        "=" * 70
    )

    entity = await resolve_source(
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

    # --------------------------------------------------------
    # Fetch
    # --------------------------------------------------------

    messages = await fetch_recent_messages(
        entity,
        since,
    )

    print(
        f"[MESSAGES FOUND] "
        f"{len(messages)}"
    )

    if not messages:

        print(
            "[SOURCE] No recent messages."
        )

        return

    # --------------------------------------------------------
    # Group
    # --------------------------------------------------------

    groups = make_groups(
        messages
    )

    print(
        f"[GROUPS FOUND] "
        f"{len(groups)}"
    )

    # --------------------------------------------------------
    # Process
    # --------------------------------------------------------

    uploaded = 0

    for index, group in enumerate(
        groups,
        start=1,
    ):

        print()
        print(
            "-" * 70
        )

        print(
            f"[GROUP {index}/{len(groups)}]"
        )

        print(
            f"[GROUP MESSAGE IDS] "
            f"{[m.id for m in group]}"
        )

        print(
            f"[GROUPED IDS] "
            f"{[m.grouped_id for m in group]}"
        )

        print(
            f"[GROUP SIZE] "
            f"{len(group)}"
        )

        # ----------------------------------------------------
        # ONLY ONE video check per group
        # ----------------------------------------------------

        video_count = sum(
            1
            for m in group
            if is_video(m)
        )

        print(
            f"[GROUP VIDEO COUNT] "
            f"{video_count}"
        )

        if video_count == 0:

            print(
                "[SKIP] "
                "No video in this group."
            )

            continue

        # ----------------------------------------------------
        # Upload
        # ----------------------------------------------------

        try:

            uploaded += await upload_videos(
                group,
                topic_id,
            )

        except Exception as exc:

            print(
                f"[GROUP UPLOAD FAILED] "
                f"group={index} "
                f"type={type(exc).__name__} "
                f"message={exc}"
            )

            # 다른 그룹은 계속 처리
            continue

    print()
    print(
        f"[SOURCE COMPLETE] "
        f"uploaded={uploaded}"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    # --------------------------------------------------------
    # DB
    # --------------------------------------------------------

    init_db()

    # --------------------------------------------------------
    # Time
    # --------------------------------------------------------

    now = datetime.now(
        UTC
    )

    lookback_since = (
        now
        - timedelta(
            minutes=LOOKBACK_MINUTES
        )
    )

    since = max(
        lookback_since,
        CUTOFF_TIME,
    )

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    print()
    print(
        "=" * 70
    )

    print(
        "Telegram Scheduled Video Processor"
    )

    print(
        f"[PROCESSOR VERSION] "
        f"{PROCESSOR_VERSION}"
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
        f"[DATABASE] "
        f"processed={count_processed()}"
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # Telegram login
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Connecting..."
    )

    await client.start()

    me = await client.get_me()

    print(
        f"[TELEGRAM] Logged in as "
        f"{getattr(me, 'first_name', '')} "
        f"(id={me.id})"
    )

    # --------------------------------------------------------
    # Sources
    # --------------------------------------------------------

    total_sources = len(
        SOURCE_MAPPING
    )

    for index, (
        source,
        topic_id,
    ) in enumerate(
        SOURCE_MAPPING,
        start=1,
    ):

        print()
        print(
            f"[SOURCE {index}/{total_sources}]"
        )

        try:

            await process_source(
                source,
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

    # --------------------------------------------------------
    # Finish
    # --------------------------------------------------------

    print()
    print(
        "=" * 70
    )

    print(
        "JOB FINISHED"
    )

    print(
        f"[DATABASE] "
        f"processed={count_processed()}"
    )

    print(
        "=" * 70
    )


# ============================================================
# ENTRY POINT
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
            f"type={type(exc).__name__}"
        )

        print(
            f"message={exc}"
        )

        print(
            "=" * 70
        )

        raise
