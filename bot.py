import os
import asyncio
import logging
import time

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InputMediaPhoto
from pyrogram.enums import ChatAction

from downloader import (
    extract_urls, download_media, cleanup_media, cleanup_old_files,
    get_platform, URL_PATTERN,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PLATFORM_EMOJI = {
    "tiktok": "\U0001f3b5",
    "youtube": "\u25b6\ufe0f",
    "instagram": "\U0001f4f7",
    "twitter": "\U0001d54f",
    "unknown": "\U0001f3ac",
}

BOT_API_LIMIT = 50 * 1024 * 1024

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

BOT_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Client(
    "botik_dodik",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
)

processing = set()
http_session: aiohttp.ClientSession = None


async def get_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()
    return http_session


async def bot_api_send_video(chat_id, file_path, caption, reply_to, duration=None, width=None, height=None, thumb_path=None):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("video", open(file_path, "rb"), filename="video.mp4", content_type="video/mp4")
    if caption:
        data.add_field("caption", caption)
        data.add_field("parse_mode", "Markdown")
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))
    if duration:
        data.add_field("duration", str(duration))
    if width:
        data.add_field("width", str(width))
    if height:
        data.add_field("height", str(height))
    data.add_field("supports_streaming", "true")
    if thumb_path and os.path.exists(thumb_path):
        data.add_field("thumbnail", open(thumb_path, "rb"), filename="thumb.jpg", content_type="image/jpeg")

    session = await get_session()
    async with session.post(f"{BOT_API_URL}/sendVideo", data=data, timeout=aiohttp.ClientTimeout(total=120)) as resp:
        result = await resp.json()
        if not result.get("ok"):
            raise Exception(result.get("description", "Bot API sendVideo failed"))
        return result


async def bot_api_send_photo(chat_id, file_path, caption, reply_to):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("photo", open(file_path, "rb"), filename="photo.jpg", content_type="image/jpeg")
    if caption:
        data.add_field("caption", caption)
        data.add_field("parse_mode", "Markdown")
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))

    session = await get_session()
    async with session.post(f"{BOT_API_URL}/sendPhoto", data=data, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        result = await resp.json()
        if not result.get("ok"):
            raise Exception(result.get("description", "Bot API sendPhoto failed"))
        return result


async def bot_api_send_media_group(chat_id, photo_paths, caption, reply_to):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))

    media_list = []
    for i, path in enumerate(photo_paths[:10]):
        field_name = f"photo{i}"
        data.add_field(field_name, open(path, "rb"), filename=f"photo{i}.jpg", content_type="image/jpeg")
        entry = {"type": "photo", "media": f"attach://{field_name}"}
        if i == 0 and caption:
            entry["caption"] = caption
            entry["parse_mode"] = "Markdown"
        media_list.append(entry)

    import json
    data.add_field("media", json.dumps(media_list))

    session = await get_session()
    async with session.post(f"{BOT_API_URL}/sendMediaGroup", data=data, timeout=aiohttp.ClientTimeout(total=120)) as resp:
        result = await resp.json()
        if not result.get("ok"):
            raise Exception(result.get("description", "Bot API sendMediaGroup failed"))
        return result


def _progress_callback(status_msg):
    last_edit = {"t": 0}

    async def _progress(current, total):
        now = time.time()
        if now - last_edit["t"] < 5:
            return
        last_edit["t"] = now
        pct = current * 100 / total
        bar_filled = int(pct // 5)
        bar = "\u2588" * bar_filled + "\u2591" * (20 - bar_filled)
        mb_done = current / 1024 / 1024
        mb_total = total / 1024 / 1024
        try:
            await status_msg.edit_text(
                f"\u2b06\ufe0f Uploading\u2026\n"
                f"`{bar}` {pct:.0f}%\n"
                f"{mb_done:.1f} / {mb_total:.1f} MB"
            )
        except Exception:
            pass

    return _progress


@app.on_message(filters.command("start"))
async def start(_client: Client, message: Message):
    await message.reply_text(
        "\U0001f3ac **Media Downloader**\n\n"
        "Send a link from:\n"
        "\u2022 TikTok (videos + photos)\n"
        "\u2022 YouTube\n"
        "\u2022 X.com / Twitter (videos + photos)\n"
        "\u2022 Instagram (videos + photos)\n\n"
        "Works in groups \u2014 just drop a link. Up to **2 GB** uploads."
    )


@app.on_message(filters.regex(URL_PATTERN))
async def handle_message(_client: Client, message: Message):
    if not message.text:
        return

    urls = extract_urls(message.text)
    if not urls:
        return

    for url in urls[:3]:
        url_hash = hash(url)
        if url_hash in processing:
            continue
        processing.add(url_hash)

        try:
            platform = get_platform(url)
            emoji = PLATFORM_EMOJI.get(platform, "\U0001f3ac")

            status = await message.reply_text(
                f"{emoji} Downloading\u2026", quote=True)

            media, error = await download_media(url)

            if error:
                await status.edit_text(error)
                asyncio.get_event_loop().call_later(
                    10, lambda m=status: asyncio.ensure_future(_safe_delete(m)))
                continue

            try:
                if media.media_type == "photos" and media.photo_paths:
                    await status.edit_text("\u2b06\ufe0f Uploading\u2026")

                    if len(media.photo_paths) == 1:
                        await bot_api_send_photo(
                            message.chat.id, media.photo_paths[0],
                            f"{emoji} **{media.title}**", message.id)
                    else:
                        await bot_api_send_media_group(
                            message.chat.id, media.photo_paths,
                            f"{emoji} **{media.title}**", message.id)
                    await status.delete()

                elif media.file_size < BOT_API_LIMIT:
                    await status.edit_text("\u2b06\ufe0f Uploading\u2026")

                    size_mb = media.file_size / 1024 / 1024
                    size_str = f"{size_mb:.1f} MB"
                    caption = f"{emoji} **{media.title}**\n{size_str}"
                    if len(caption) > 1024:
                        caption = caption[:1021] + "\u2026"

                    await bot_api_send_video(
                        message.chat.id, media.file_path, caption, message.id,
                        duration=media.duration, width=media.width, height=media.height,
                        thumb_path=media.thumbnail_path)
                    await status.delete()

                else:
                    await _client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
                    await status.edit_text("\u2b06\ufe0f Uploading large file\u2026")

                    size_mb = media.file_size / 1024 / 1024
                    size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
                    caption = f"{emoji} **{media.title}**\n{size_str}"
                    if len(caption) > 1024:
                        caption = caption[:1021] + "\u2026"

                    await message.reply_video(
                        video=media.file_path,
                        caption=caption,
                        quote=True,
                        supports_streaming=True,
                        duration=media.duration or None,
                        width=media.width or None,
                        height=media.height or None,
                        thumb=media.thumbnail_path,
                        progress=_progress_callback(status),
                    )
                    await status.delete()

            except Exception as e:
                logger.error("Upload error: %s", e)
                await status.edit_text("\u274c Upload failed")
            finally:
                if media.file_path:
                    cleanup_media(media.file_path)

        finally:
            processing.discard(url_hash)


async def _safe_delete(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass


async def _cleanup_loop():
    while True:
        await asyncio.sleep(300)
        await cleanup_old_files()


if __name__ == "__main__":
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        raise RuntimeError(
            "Set API_ID, API_HASH, and TELEGRAM_BOT_TOKEN environment variables"
        )
    logger.info("Bot starting (hybrid: Bot API <50MB, MTProto >50MB)")
    app.start()
    asyncio.get_event_loop().create_task(_cleanup_loop())
    from pyrogram import idle
    idle()
    app.stop()
