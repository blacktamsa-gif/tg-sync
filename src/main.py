import os
import sys
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

from database import (
    count_processed,
    is_processed,
    mark_processed_many,
)


# ============================================================
# VERSION
# ============================================================

PROCESSOR_VERSION = "2026-08-26-LOOKBACK-130-CLEAN-02"


# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION = os.environ.get("SESSION", "")

TARGET_CHAT = os.environ.get("TARGET_CHAT", "")

SOURCE_A = os.environ.get("SOURCE_A", "")
SOURCE_B = os.environ.get("SOURCE_B", "")
SOURCE_C = os.environ.get("SOURCE_C", "")
SOURCE_D = os.environ.get("SOURCE_D", "")

TOPIC_A = os.environ.get("TOPIC_A", "")
TOPIC_B = os.environ.get("TOPIC_B", "")


# ============================================================
# TIME SETTINGS
# ============================================================

KST = timezone(timedelta(hours=9))

# 최초 실행 기준.
#
# 2026-08-25 18:00:00 KST
#
# 즉 이 시간보다 이전에 올라온 영상은 가져오지 않는다.
INITIAL_CUTOFF_KST = datetime(
    2026,
    8,
    25,
    18,
    0,
    0,
    tzinfo=KST,
)

# GitHub Actions 실행 지연을 고려한 검색 범위.
#
# 예:
# 05:20 실행
# → 03:10 이후 메시지를 검색
#
# SQLite가 중복 업로드를 막기 때문에
# 범위를 넓혀도 이미 처리한 영상은 다시 업로드하지 않는다.
LOOKBACK_MINUTES = 130


# ============================================================
# BASIC VALIDATION
# ============================================================

def require_environment():
    required = {
        "API_ID": API_ID,
        "API_HASH": API_HASH,
        "SESSION": SESSION,
        "TARGET_CHAT": TARGET_CHAT,
        "SOURCE_A": SOURCE_A,
        "SOURCE_B": SOURCE_B,
        "SOURCE_C": SOURCE_C,
        "SOURCE_D": SOURCE_D,
        "TOPIC_A": TOPIC_A,
        "TOPIC_B": TOPIC_B,
    }

    missing = []

    for key, value in required.items():
        if value is None or str(value).strip() == "" or value == 0:
            missing.append(key)

    if missing:
        print(
            "[CONFIG ERROR] Missing environment variables:",
            ", ".join(missing),
            flush=True,
        )
        sys.exit(1)


# ============================================================
# TIME HELPERS
# ============================================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_kst(dt: datetime) -> datetime:
    return dt.astimezone(KST)


def get_since_time(now: datetime) -> datetime:
    lookback_since = now - timedelta(minutes=LOOKBACK_MINUTES)

    if INITIAL_CUTOFF_KST > lookback_since.astimezone(KST):
        return INITIAL_CUTOFF_KST.astimezone(timezone.utc)

    return lookback_since


# ============================================================
# SOURCE / DESTINATION CONFIG
# ============================================================

def source_configs():
    return [
        {
            "name": "SOURCE_A",
            "source": SOURCE_A,
            "topic": TOPIC_A,
        },
        {
            "name": "SOURCE_B",
            "source": SOURCE_B,
            "topic": TOPIC_A,
        },
        {
            "name": "SOURCE_C",
            "source": SOURCE_C,
            "topic": TOPIC_B,
        },
        {
            "name": "SOURCE_D",
            "source": SOURCE_D,
            "topic": TOPIC_B,
        },
    ]


# ============================================================
# TELEGRAM ENTITY RESOLUTION
# ============================================================

def normalize_numeric_id(value: str):
    value = str(value).strip()

    try:
        return int(value)
    except ValueError:
        return None


async def resolve_entity(client: TelegramClient, source: str):
    source = str(source).strip()

    print(f"[RESOLVE] source={source}", flush=True)

    numeric_id = normalize_numeric_id(source)

    # --------------------------------------------------------
    # 1. Numeric Telegram ID
    # --------------------------------------------------------

    if numeric_id is not None:

        try:
            entity = await client.get_entity(numeric_id)

            print(
                f"[RESOLVE SUCCESS] get_entity numeric={numeric_id}",
                flush=True,
            )

            return entity

        except Exception as exc:
            print(
                f"[RESOLVE] get_entity numeric failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    # --------------------------------------------------------
    # 2. Username
    # --------------------------------------------------------

    username = source

    if username.startswith("@"):
        username = username[1:]

    if username:

        try:
            entity = await client.get_entity(username)

            print(
                f"[RESOLVE SUCCESS] username={username}",
                flush=True,
            )

            return entity

        except Exception as exc:
            print(
                f"[RESOLVE] username failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    # --------------------------------------------------------
    # 3. Search through dialogs
    # --------------------------------------------------------

    print("[DIALOGS] Loading Telegram dialogs...", flush=True)

    dialogs = await client.get_dialogs(limit=None)

    print(
        f"[DIALOGS] Loaded {len(dialogs)} dialogs.",
        flush=True,
    )

    # Exact numeric peer matching
    if numeric_id is not None:

        for dialog in dialogs:

            entity = dialog.entity

            raw_id = getattr(entity, "id", None)

            if raw_id == numeric_id:
                print(
                    f"[RESOLVE SUCCESS] Matched raw ID {raw_id}",
                    flush=True,
                )

                return entity

            # Telegram supergroup/channel IDs are often represented
            # as -100xxxxxxxxxx by Peer ID.
            if numeric_id < 0 and raw_id == numeric_id + 1000000000000:
                print(
                    f"[RESOLVE SUCCESS] Matched Telegram -100 ID "
                    f"{numeric_id}",
                    flush=True,
                )

                return entity

            if numeric_id > 0 and raw_id == numeric_id:
                print(
                    f"[RESOLVE SUCCESS] Matched raw entity ID {raw_id}",
                    flush=True,
                )

                return entity

    # --------------------------------------------------------
    # Username matching
    # --------------------------------------------------------

    source_username = username.lower()

    for dialog in dialogs:

        entity = dialog.entity

        entity_username = getattr(entity, "username", None)

        if entity_username:
            if entity_username.lower() == source_username:

                print(
                    f"[RESOLVE SUCCESS] Matched username "
                    f"@{entity_username}",
                    flush=True,
                )

                return entity

    # --------------------------------------------------------
    # Name matching
    # --------------------------------------------------------

    for dialog in dialogs:

        entity = dialog.entity

        title = (
            getattr(entity, "title", None)
            or getattr(entity, "first_name", None)
            or ""
        )

        if title and title.lower() == source.lower():

            print(
                f"[RESOLVE SUCCESS] Matched title={title}",
                flush=True,
            )

            return entity

    raise ValueError(
        f"Cannot find Telegram entity: {source}"
    )


# ============================================================
# VIDEO DETECTION
# ============================================================

def is_video_message(message) -> bool:
    """
    True only for actual Telegram video media.

    Images / photos / text / documents are ignored.
    """

    if message is None:
        return False

    if getattr(message, "video", None) is not None:
        return True

    return False


# ============================================================
# GROUP / ALBUM HANDLING
# ============================================================

def build_message_groups(messages):
    """
    Group Telegram messages by grouped_id.

    Telegram album:
        grouped_id = same value

    Normal message:
        grouped_id = None

    Result:
        [
            [message],
            [message1, message2, message3],
            ...
        ]
    """

    groups = []

    grouped = {}

    for message in messages:

        grouped_id = getattr(message, "grouped_id", None)

        if grouped_id is None:

            groups.append([message])

            continue

        if grouped_id not in grouped:
            grouped[grouped_id] = []

        grouped[grouped_id].append(message)

    # Keep album groups in chronological message order.
    for grouped_id, group in grouped.items():

        group.sort(
            key=lambda msg: getattr(msg, "id", 0)
        )

        groups.append(group)

    # Process groups in chronological order.
    groups.sort(
        key=lambda group: getattr(group[0], "id", 0)
    )

    return groups


# ============================================================
# MESSAGE DESCRIPTION
# ============================================================

def print_group_info(group, index, total):
    message_ids = [
        getattr(message, "id", None)
        for message in group
    ]

    grouped_ids = [
        getattr(message, "grouped_id", None)
        for message in group
    ]

    video_count = sum(
        1
        for message in group
        if is_video_message(message)
    )

    print("", flush=True)
    print("-" * 70, flush=True)

    print(
        f"[GROUP {index}/{total}]",
        flush=True,
    )

    print(
        f"[GROUP MESSAGE IDS] {message_ids}",
        flush=True,
    )

    print(
        f"[GROUPED IDS] {grouped_ids}",
        flush=True,
    )

    print(
        f"[GROUP SIZE] {len(group)}",
        flush=True,
    )

    print(
        f"[GROUP VIDEO COUNT] {video_count}",
        flush=True,
    )

    return video_count


# ============================================================
# DOWNLOAD
# ============================================================

async def download_video(
    client: TelegramClient,
    message,
    temp_dir: Path,
):
    message_id = message.id

    print(
        f"[DOWNLOAD START] message={message_id}",
        flush=True,
    )

    try:

        file_path = await client.download_media(
            message,
            file=str(temp_dir),
        )

        if not file_path:
            raise RuntimeError(
                "Telethon returned no downloaded file path."
            )

        path = Path(file_path)

        if not path.exists():
            raise RuntimeError(
                f"Downloaded path does not exist: {path}"
            )

        size = path.stat().st_size

        print(
            f"[DOWNLOAD SUCCESS] "
            f"message={message_id} "
            f"size={size:,} bytes",
            flush=True,
        )

        return path

    except Exception as exc:

        print(
            f"[DOWNLOAD ERROR] "
            f"message={message_id} "
            f"type={type(exc).__name__} "
            f"message={exc}",
            flush=True,
        )

        return None


# ============================================================
# UPLOAD
# ============================================================

async def upload_videos(
    client: TelegramClient,
    target_entity,
    topic_id: int,
    files,
):
    if not files:
        return False

    print("", flush=True)
    print("=" * 60, flush=True)

    print(
        f"[UPLOAD START] "
        f"files={len(files)} "
        f"topic={topic_id}",
        flush=True,
    )

    print(
        "[UPLOAD MODE] caption=None",
        flush=True,
    )

    print(
        "[UPLOAD MODE] text=False",
        flush=True,
    )

    print(
        "[UPLOAD MODE] media_only=True",
        flush=True,
    )

    try:

        # ----------------------------------------------------
        # Album
        # ----------------------------------------------------

        if len(files) > 1:

            print(
                f"[UPLOAD ALBUM] "
                f"count={len(files)}",
                flush=True,
            )

            await client.send_file(
                target_entity,
                files,
                caption=None,
                force_document=False,
                supports_streaming=True,
                reply_to=topic_id,
            )

        # ----------------------------------------------------
        # Single video
        # ----------------------------------------------------

        else:

            print(
                "[UPLOAD SINGLE VIDEO]",
                flush=True,
            )

            await client.send_file(
                target_entity,
                files[0],
                caption=None,
                force_document=False,
                supports_streaming=True,
                reply_to=topic_id,
            )

        print(
            f"[UPLOAD SUCCESS] "
            f"videos={len(files)} "
            f"topic={topic_id}",
            flush=True,
        )

        return True

    except Exception as exc:

        print(
            f"[UPLOAD ERROR] "
            f"type={type(exc).__name__} "
            f"message={exc}",
            flush=True,
        )

        return False


# ============================================================
# PROCESS ONE SOURCE
# ============================================================

async def process_source(
    client: TelegramClient,
    source_name: str,
    source_value: str,
    target_entity,
    topic_id: int,
    since_utc: datetime,
):
    print("", flush=True)
    print("=" * 70, flush=True)

    print(
        f"[PROCESS SOURCE] {source_name}",
        flush=True,
    )

    print(
        f"[DESTINATION TOPIC] {topic_id}",
        flush=True,
    )

    print(
        f"[SINCE UTC] {since_utc.isoformat()}",
        flush=True,
    )

    print(
        f"[SINCE KST] {to_kst(since_utc).isoformat()}",
        flush=True,
    )

    print(
        "=" * 70,
        flush=True,
    )

    # --------------------------------------------------------
    # Resolve source
    # --------------------------------------------------------

    try:

        source_entity = await resolve_entity(
            client,
            source_value,
        )

    except Exception as exc:

        print(
            f"[SOURCE ERROR] "
            f"source={source_value} "
            f"type={type(exc).__name__} "
            f"message={exc}",
            flush=True,
        )

        return 0

    source_entity_id = int(
        getattr(source_entity, "id", 0)
    )

    source_title = (
        getattr(source_entity, "title", None)
        or getattr(source_entity, "username", None)
        or getattr(source_entity, "first_name", None)
        or str(source_entity_id)
    )

    print(
        f"[SOURCE ENTITY] "
        f"name='{source_title}' "
        f"id={source_entity_id}",
        flush=True,
    )

    # --------------------------------------------------------
    # Fetch messages
    #
    # IMPORTANT:
    # We do NOT specify any Telegram forum topic.
    #
    # Therefore messages from all topics are considered.
    # --------------------------------------------------------

    messages = []

    try:

        async for message in client.iter_messages(
            source_entity,
            limit=None,
            offset_date=None,
        ):

            message_date = message.date

            if message_date is None:
                continue

            message_date = message_date.astimezone(
                timezone.utc
            )

            # Newer than cutoff
            if message_date >= since_utc:

                messages.append(message)

                continue

            # Telethon returns newest -> oldest.
            #
            # Once older than our cutoff, we can stop.
            break

    except Exception as exc:

        print(
            f"[MESSAGE FETCH ERROR] "
            f"type={type(exc).__name__} "
            f"message={exc}",
            flush=True,
        )

        return 0

    print(
        f"[MESSAGES FOUND] {len(messages)}",
        flush=True,
    )

    if not messages:

        print(
            "[SOURCE COMPLETE] uploaded=0",
            flush=True,
        )

        return 0

    # --------------------------------------------------------
    # Album grouping
    # --------------------------------------------------------

    groups = build_message_groups(messages)

    print(
        f"[GROUPS FOUND] {len(groups)}",
        flush=True,
    )

    uploaded_count = 0

    # --------------------------------------------------------
    # Temporary directory
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="tg-video-"
    ) as temp_dir_string:

        temp_dir = Path(temp_dir_string)

        # ----------------------------------------------------
        # Process groups
        # ----------------------------------------------------

        for index, group in enumerate(
            groups,
            start=1,
        ):

            video_count = print_group_info(
                group,
                index,
                len(groups),
            )

            # ------------------------------------------------
            # No video
            # ------------------------------------------------

            if video_count == 0:

                print(
                    "[SKIP] No video in this group.",
                    flush=True,
                )

                continue

            # ------------------------------------------------
            # Only video messages
            #
            # This automatically removes:
            #
            # image
            # photo
            # text
            # document
            # ------------------------------------------------

            video_messages = [
                message
                for message in group
                if is_video_message(message)
            ]

            print(
                f"[VIDEO MESSAGES] "
                f"{[message.id for message in video_messages]}",
                flush=True,
            )

            # ------------------------------------------------
            # DB check
            # ------------------------------------------------

            new_video_messages = []

            for message in video_messages:

                processed = is_processed(
                    source_entity_id,
                    message.id,
                )

                print(
                    f"[CHECK DB] "
                    f"message={message.id} "
                    f"processed={processed}",
                    flush=True,
                )

                if not processed:
                    new_video_messages.append(message)

            print(
                f"[NEW VIDEOS] "
                f"{len(new_video_messages)}",
                flush=True,
            )

            if not new_video_messages:

                print(
                    "[SKIP] All videos already processed.",
                    flush=True,
                )

                continue

            # ------------------------------------------------
            # Download
            # ------------------------------------------------

            downloaded_files = []

            download_failed = False

            for message in new_video_messages:

                file_path = await download_video(
                    client,
                    message,
                    temp_dir,
                )

                if file_path is None:

                    download_failed = True

                    print(
                        f"[GROUP DOWNLOAD FAILED] "
                        f"message={message.id}",
                        flush=True,
                    )

                    break

                downloaded_files.append(
                    file_path
                )

            # ------------------------------------------------
            # If any download failed:
            #
            # DO NOT mark messages processed.
            #
            # They will be retried on next run.
            # ------------------------------------------------

            if download_failed:

                print(
                    "[GROUP FAILED] "
                    "Download failed. "
                    "Database will NOT be updated.",
                    flush=True,
                )

                continue

            # ------------------------------------------------
            # Upload
            # ------------------------------------------------

            upload_success = await upload_videos(
                client,
                target_entity,
                topic_id,
                downloaded_files,
            )

            if not upload_success:

                print(
                    "[GROUP FAILED] "
                    "Upload failed. "
                    "Database will NOT be updated.",
                    flush=True,
                )

                continue

            # ------------------------------------------------
            # Mark processed only AFTER successful upload.
            # ------------------------------------------------

            message_ids = [
                message.id
                for message in new_video_messages
            ]

            mark_processed_many(
                source_entity_id,
                message_ids,
            )

            uploaded_count += len(
                new_video_messages
            )

            print(
                f"[DATABASE] "
                f"marked={len(message_ids)}",
                flush=True,
            )

            print(
                f"[DATABASE] "
                f"total_processed={count_processed()}",
                flush=True,
            )

    print("", flush=True)

    print(
        f"[SOURCE COMPLETE] "
        f"uploaded={uploaded_count}",
        flush=True,
    )

    return uploaded_count


# ============================================================
# MAIN
# ============================================================

async def main():
    require_environment()

    current_utc = now_utc()

    since_utc = get_since_time(
        current_utc
    )

    print("=" * 70, flush=True)

    print(
        "Telegram Scheduled Video Processor",
        flush=True,
    )

    print(
        f"[PROCESSOR VERSION] "
        f"{PROCESSOR_VERSION}",
        flush=True,
    )

    print("=" * 70, flush=True)

    print(
        f"[NOW UTC] "
        f"{current_utc.isoformat()}",
        flush=True,
    )

    print(
        f"[NOW KST] "
        f"{to_kst(current_utc).isoformat()}",
        flush=True,
    )

    print(
        f"[INITIAL CUTOFF KST] "
        f"{INITIAL_CUTOFF_KST.isoformat()}",
        flush=True,
    )

    print(
        f"[INITIAL CUTOFF UTC] "
        f"{INITIAL_CUTOFF_KST.astimezone(timezone.utc).isoformat()}",
        flush=True,
    )

    print(
        f"[LOOKBACK] "
        f"{LOOKBACK_MINUTES} minutes",
        flush=True,
    )

    print(
        f"[SINCE UTC] "
        f"{since_utc.isoformat()}",
        flush=True,
    )

    print(
        f"[SINCE KST] "
        f"{to_kst(since_utc).isoformat()}",
        flush=True,
    )

    print(
        f"[TARGET CHAT] "
        f"{TARGET_CHAT}",
        flush=True,
    )

    print(
        f"[TOPIC A] "
        f"{TOPIC_A}",
        flush=True,
    )

    print(
        f"[TOPIC B] "
        f"{TOPIC_B}",
        flush=True,
    )

    print(
        f"[DATABASE] "
        f"processed={count_processed()}",
        flush=True,
    )

    print(
        "=" * 70,
        flush=True,
    )

    # --------------------------------------------------------
    # Client
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Connecting...",
        flush=True,
    )

    client = TelegramClient(
        StringSession(SESSION),
        API_ID,
        API_HASH,
    )

    await client.start()

    me = await client.get_me()

    print(
        f"[TELEGRAM] Logged in as "
        f"{getattr(me, 'first_name', '')} "
        f"(id={getattr(me, 'id', '')})",
        flush=True,
    )

    # --------------------------------------------------------
    # Resolve destination
    # --------------------------------------------------------

    try:

        target_entity = await resolve_entity(
            client,
            TARGET_CHAT,
        )

    except Exception as exc:

        print(
            f"[TARGET ERROR] "
            f"type={type(exc).__name__} "
            f"message={exc}",
            flush=True,
        )

        await client.disconnect()

        sys.exit(1)

    print(
        f"[TARGET ENTITY] "
        f"name='"
        f"{getattr(target_entity, 'title', None) or getattr(target_entity, 'username', None)}"
        f"' "
        f"id={getattr(target_entity, 'id', None)}",
        flush=True,
    )

    # --------------------------------------------------------
    # Sources
    # --------------------------------------------------------

    configs = source_configs()

    total_uploaded = 0

    # --------------------------------------------------------
    # Process each source
    # --------------------------------------------------------

    for index, config in enumerate(
        configs,
        start=1,
    ):

        print("", flush=True)

        print(
            f"[SOURCE {index}/{len(configs)}]",
            flush=True,
        )

        uploaded = await process_source(
            client=client,
            source_name=config["name"],
            source_value=config["source"],
            target_entity=target_entity,
            topic_id=int(config["topic"]),
            since_utc=since_utc,
        )

        total_uploaded += uploaded

    # --------------------------------------------------------
    # Finish
    # --------------------------------------------------------

    print("", flush=True)
    print("=" * 70, flush=True)

    print(
        "JOB FINISHED",
        flush=True,
    )

    print(
        f"[TOTAL UPLOADED] "
        f"{total_uploaded}",
        flush=True,
    )

    print(
        f"[DATABASE] "
        f"processed={count_processed()}",
        flush=True,
    )

    print(
        "=" * 70,
        flush=True,
    )

    await client.disconnect()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "[STOPPED] KeyboardInterrupt",
            flush=True,
        )

    except Exception as exc:

        print(
            "",
            flush=True,
        )

        print(
            "=" * 70,
            flush=True,
        )

        print(
            "[FATAL ERROR]",
            flush=True,
        )

        print(
            f"type={type(exc).__name__}",
            flush=True,
        )

        print(
            f"message={exc}",
            flush=True,
        )

        print(
            "=" * 70,
            flush=True,
        )

        raise
