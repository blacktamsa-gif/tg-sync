import os
import asyncio
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo, MessageMediaDocument

from database import is_processed, mark_processed

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION = os.environ["SESSION"]

TARGET_CHAT = os.environ["TARGET_CHAT"]
TOPIC_A = int(os.environ["TOPIC_A"])
TOPIC_B = int(os.environ["TOPIC_B"])

SOURCE_MAPPING = {
    os.environ["SOURCE_A"]: TOPIC_A,
    os.environ["SOURCE_B"]: TOPIC_A,
    os.environ["SOURCE_C"]: TOPIC_B,
    os.environ["SOURCE_D"]: TOPIC_B,
}

UTC = timezone.utc

# 2026-08-25 18:00 KST = 2026-08-25 09:00 UTC
CUTOFF_TIME = datetime(2026, 8, 25, 9, 0, 0, tzinfo=UTC)
LOOKBACK_MINUTES = 70

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

def normalize_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def is_video_message(message) -> bool:
    if message is None or not message.media:
        return False
    if not isinstance(message.media, MessageMediaDocument):
        return False
    document = message.document
    if document is None:
        return False
    return any(
        isinstance(attribute, DocumentAttributeVideo)
        for attribute in document.attributes
    )

def get_message_group_key(message):
    if message.grouped_id is not None:
        return ("album", message.grouped_id)
    return ("single", message.id)

def calculate_since() -> datetime:
    now = datetime.now(UTC)
    lookback = now - timedelta(minutes=LOOKBACK_MINUTES)
    return max(lookback, CUTOFF_TIME)

async def collect_recent_messages(source, since: datetime):
    entity = await client.get_entity(source)
    collected = []
    now = datetime.now(UTC)

    async for message in client.iter_messages(entity, reverse=True):
        if not message.date:
            continue
        message_time = normalize_datetime(message.date)
        if message_time < CUTOFF_TIME:
            continue
        if message_time < since:
            continue
        if message_time > now:
            continue
        collected.append(message)

    return collected

def group_messages(messages):
    groups = {}
    for message in messages:
        key = get_message_group_key(message)
        groups.setdefault(key, []).append(message)
    for key in groups:
        groups[key].sort(key=lambda message: message.id)
    return sorted(groups.values(), key=lambda group: group[0].id)

async def send_video_group(messages, target_chat, topic_id):
    video_messages = [m for m in messages if is_video_message(m)]
    if not video_messages:
        return

    new_video_messages = [
        m for m in video_messages
        if not is_processed(int(m.chat_id), int(m.id))
    ]
    if not new_video_messages:
        return

    media = [m.media for m in new_video_messages]

    await client.send_file(
        target_chat,
        media,
        caption=None,
        reply_to=topic_id,
    )

    processed_at = datetime.now(UTC).isoformat()
    mark_processed(
        [(int(m.chat_id), int(m.id)) for m in new_video_messages],
        processed_at,
    )

async def process_source(source, target_chat, topic_id, since):
    messages = await collect_recent_messages(source, since)
    if not messages:
        return

    for group in group_messages(messages):
        try:
            await send_video_group(group, target_chat, topic_id)
        except Exception as exc:
            print(f"Album processing error: {type(exc).__name__}")

async def main():
    since = calculate_since()
    print("Job started")
    print("Processing messages after:", since.isoformat())

    await client.start()
    if await client.get_me() is None:
        raise RuntimeError("Telegram authentication failed")

    for source, topic_id in SOURCE_MAPPING.items():
        try:
            await process_source(source, TARGET_CHAT, topic_id, since)
        except Exception as exc:
            print(f"Source processing error: {type(exc).__name__}")

    print("Job finished")

if __name__ == "__main__":
    asyncio.run(main())
