import os
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.types import (
    DocumentAttributeVideo,
    MessageMediaDocument,
    InputReplyToMessage,
)

from database import (
    init_db,
    is_processed,
    mark_processed,
    count_processed,
)


# ============================================================
# Time
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
# Secrets
# ============================================================

def required_secret(name: str) -> str:

    value = os.environ.get(
        name,
        "",
    ).strip()

    if not value:

        raise RuntimeError(
            f"Required environment variable "
            f"'{name}' is missing or empty."
        )

    return value


try:

    API_ID = int(
        required_secret("API_ID")
    )

except ValueError:

    raise RuntimeError(
        "API_ID must contain numbers only."
    )


API_HASH = required_secret(
    "API_HASH"
)

SESSION = required_secret(
    "SESSION"
)

TARGET_CHAT = int(
    required_secret("TARGET_CHAT")
)

TOPIC_A = int(
    required_secret("TOPIC_A")
)

TOPIC_B = int(
    required_secret("TOPIC_B")
)

SOURCE_A = required_secret(
    "SOURCE_A"
)

SOURCE_B = required_secret(
    "SOURCE_B"
)

SOURCE_C = required_secret(
    "SOURCE_C"
)

SOURCE_D = required_secret(
    "SOURCE_D"
)


# ============================================================
# Source mapping
# ============================================================

SOURCE_MAPPING = {
    SOURCE_A: TOPIC_A,
    SOURCE_B: TOPIC_A,
    SOURCE_C: TOPIC_B,
    SOURCE_D: TOPIC_B,
}


# ============================================================
# Telegram
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
)


# ============================================================
# Dialog cache
# ============================================================

DIALOG_CACHE = None


async def load_dialog_cache():

    global DIALOG_CACHE

    if DIALOG_CACHE is not None:

        return DIALOG_CACHE

    print(
        "[DIALOGS] Loading Telegram dialogs..."
    )

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

    DIALOG_CACHE = {
        "peer_id": by_peer_id,
        "raw_id": by_raw_id,
        "username": by_username,
    }

    print(
        f"[DIALOGS] Loaded {len(dialogs)} dialogs."
    )

    return DIALOG_CACHE


# ============================================================
# Resolve entity
# ============================================================

async def resolve_entity(
    source: str,
):

    source = str(
        source
    ).strip()

    cache = await load_dialog_cache()

    print(
        f"[RESOLVE] Trying source={source}"
    )

    # Peer ID
    entity = cache["peer_id"].get(
        source
    )

    if entity:

        print(
            "[RESOLVE SUCCESS] "
            f"Matched Peer ID {source}"
        )

        return entity

    # Raw ID
    entity = cache["raw_id"].get(
        source
    )

    if entity:

        print(
            "[RESOLVE SUCCESS] "
            f"Matched Raw ID {source}"
        )

        return entity

    # Username
    username = source.lstrip(
        "@"
    ).lower()

    entity = cache["username"].get(
        username
    )

    if entity:

        print(
            "[RESOLVE SUCCESS] "
            f"Matched username @{username}"
        )

        return entity

    # Fallback
    try:

        entity = await client.get_entity(
            source
        )

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
# Date
# ============================================================

def normalize_datetime(
    value: datetime,
) -> datetime:

    if value.tzinfo is None:

        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


def calculate_since():

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
# Grouping
# ============================================================

def group_messages(
    messages,
):

    groups = {}

    for message in messages:

        if message.grouped_id:

            key = (
                "album",
                int(
                    message.grouped_id
                ),
            )

        else:

            key = (
                "single",
                int(
                    message.id
                ),
            )

        groups.setdefault(
            key,
            [],
        ).append(
            message
        )

    for group in groups.values():

        group.sort(
            key=lambda x: x.id
        )

    result = list(
        groups.values()
    )

    result.sort(
        key=lambda x: x[0].id
    )

    return result


# ============================================================
# Collect messages
# ============================================================

async def collect_messages(
    entity,
    since,
):

    messages = []

    now = datetime.now(
        UTC
    )

    async for message in client.iter_messages(
        entity
    ):

        if not message.date:

            continue

        message_time = normalize_datetime(
            message.date
        )

        if message_time > now:

            continue

        if message_time < CUTOFF_TIME:

            break

        if message_time < since:

            break

        messages.append(
            message
        )

    return messages


# ============================================================
# Topic reply
# ============================================================

def create_topic_reply(
    topic_id: int,
):

    return InputReplyToMessage(
        reply_to_msg_id=int(
            topic_id
        ),
        top_msg_id=int(
            topic_id
        ),
        quote=False,
    )


# ============================================================
# Download one video
# ============================================================

async def download_video(
    message,
    directory,
):

    source_chat_id = int(
        message.chat_id
    )

    message_id = int(
        message.id
    )

    print(
        f"[DOWNLOAD START] "
        f"source={source_chat_id} "
        f"message={message_id}"
    )

    # Telegram이 제공하는 파일 확장자를 최대한 유지한다.
    extension = ".mp4"

    try:

        document = message.document

        if document:

            for attribute in document.attributes:

                file_name = getattr(
                    attribute,
                    "file_name",
                    None,
                )

                if file_name:

                    _, ext = os.path.splitext(
                        file_name
                    )

                    if ext:

                        extension = ext

                    break

    except Exception:

        pass

    filename = (
        f"video_"
        f"{source_chat_id}_"
        f"{message_id}"
        f"{extension}"
    )

    path = os.path.join(
        directory,
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
            f"source={source_chat_id} "
            f"message={message_id} "
            f"type={type(exc).__name__} "
            f"message={exc}"
        )

        raise

    if not downloaded:

        raise RuntimeError(
            "Telegram returned no downloaded file."
        )

    if not os.path.exists(
        downloaded
    ):

        raise RuntimeError(
            f"Downloaded file does not exist: "
            f"{downloaded}"
        )

    size = os.path.getsize(
        downloaded
    )

    print(
        f"[DOWNLOAD SUCCESS] "
        f"message={message_id} "
        f"size={size:,} bytes "
        f"path={downloaded}"
    )

    return downloaded


# ============================================================
# Upload videos
# ============================================================

async def upload_video_group(
    messages,
    topic_id,
):

    # --------------------------------------------------------
    # 동영상만 추출
    # --------------------------------------------------------

    videos = [
        message
        for message in messages
        if is_video_message(message)
    ]

    print(
        f"[GROUP] "
        f"total_messages={len(messages)} "
        f"video_messages={len(videos)}"
    )

    if not videos:

        print(
            "[SKIP] No video."
        )

        return

    # --------------------------------------------------------
    # 중복 검사
    # --------------------------------------------------------

    new_videos = []

    for message in videos:

        source_chat_id = int(
            message.chat_id
        )

        message_id = int(
            message.id
        )

        if is_processed(
            source_chat_id,
            message_id,
        ):

            print(
                f"[DUPLICATE] "
                f"source={source_chat_id} "
                f"message={message_id}"
            )

            continue

        print(
            f"[VIDEO FOUND] "
            f"source={source_chat_id} "
            f"message={message_id}"
        )

        new_videos.append(
            message
        )

    if not new_videos:

        print(
            "[SKIP] "
            "All videos already processed."
        )

        return

    # --------------------------------------------------------
    # Temporary directory
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="tg_video_"
    ) as temp_dir:

        downloaded_files = []

        try:

            # =================================================
            # Download
            # =================================================

            for message in new_videos:

                path = await download_video(
                    message,
                    temp_dir,
                )

                downloaded_files.append(
                    path
                )

            if not downloaded_files:

                raise RuntimeError(
                    "No video files were downloaded."
                )

            # =================================================
            # Upload
            # =================================================

            topic_reply = create_topic_reply(
                topic_id
            )

            print(
                f"[UPLOAD START] "
                f"videos={len(downloaded_files)} "
                f"topic={topic_id}"
            )

            print(
                "[UPLOAD] "
                "caption=None"
            )

            print(
                "[UPLOAD] "
                "quote=False"
            )

            # ------------------------------------------------
            # Single video
            # ------------------------------------------------

            if len(downloaded_files) == 1:

                await client.send_file(
                    entity=TARGET_CHAT,
                    file=downloaded_files[0],
                    caption=None,
                    force_document=False,
                    reply_to=topic_reply,
                )

            # ------------------------------------------------
            # Multiple videos = Telegram album
            # ------------------------------------------------

            else:

                await client.send_file(
                    entity=TARGET_CHAT,
                    file=downloaded_files,
                    caption=None,
                    force_document=False,
                    reply_to=topic_reply,
                )

            print(
                f"[UPLOAD SUCCESS] "
                f"videos={len(downloaded_files)} "
                f"topic={topic_id}"
            )

            # =================================================
            # DB
            # =================================================

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
                    for message in new_videos
                ],
                processed_at,
            )

            print(
                f"[DATABASE] "
                f"marked={len(new_videos)}"
            )

            print(
                f"[DATABASE] "
                f"total_processed={count_processed()}"
            )

        except Exception as exc:

            print(
                "[VIDEO GROUP FAILED]"
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
            # 업로드 실패 시 DB에 기록하지 않는다.
            # 다음 실행에서 다시 시도할 수 있다.
            # ------------------------------------------------

            raise


# ============================================================
# Process source
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

    entity = await resolve_entity(
        source
    )

    title = getattr(
        entity,
        "title",
        None,
    )

    raw_id = getattr(
        entity,
        "id",
        None,
    )

    print(
        f"[SOURCE ENTITY] "
        f"name={title!r} "
        f"id={raw_id}"
    )

    messages = await collect_messages(
        entity,
        since,
    )

    print(
        f"[MESSAGES FOUND] "
        f"{len(messages)}"
    )

    if not messages:

        print(
            "[SOURCE] No messages."
        )

        return

    groups = group_messages(
        messages
    )

    print(
        f"[GROUPS FOUND] "
        f"{len(groups)}"
    )

    # --------------------------------------------------------
    # 각각의 메시지/앨범 처리
    # --------------------------------------------------------

    for index, group in enumerate(
        groups,
        start=1,
    ):

        print()
        print(
            "-" * 60
        )

        print(
            f"[GROUP {index}/{len(groups)}]"
        )

        print(
            f"[GROUP MESSAGE IDS] "
            f"{[message.id for message in group]}"
        )

        print(
            f"[GROUP GROUPED IDS] "
            f"{[message.grouped_id for message in group]}"
        )

        try:

            await upload_video_group(
                group,
                topic_id,
            )

        except Exception as exc:

            print(
                f"[GROUP FAILED] "
                f"source={source} "
                f"group={index} "
                f"type={type(exc).__name__} "
                f"message={exc}"
            )

            # 한 그룹이 실패해도
            # 다른 그룹은 계속 처리한다.
            continue


# ============================================================
# Main
# ============================================================

async def main():

    # --------------------------------------------------------
    # DB 초기화
    # --------------------------------------------------------

    init_db()

    # --------------------------------------------------------
    # Time
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
        f"[NOW UTC] {now.isoformat()}"
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
    # Telegram
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Connecting..."
    )

    await client.start()

    me = await client.get_me()

    if me is None:

        raise RuntimeError(
            "Telegram login failed."
        )

    print(
        f"[TELEGRAM] Logged in as "
        f"{getattr(me, 'first_name', '')} "
        f"(id={me.id})"
    )

    # --------------------------------------------------------
    # Sources
    # --------------------------------------------------------

    total = len(
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
            f"[SOURCE {index}/{total}]"
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

            continue

    # --------------------------------------------------------
    # Finished
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
# Entry
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
