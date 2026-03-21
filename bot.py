import os
import json
import asyncio
import logging

import aiohttp

from downloader import (
    extract_urls, download_media, cleanup_media, cleanup_old_files,
    get_platform,
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

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def escape_md(text: str) -> str:
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)

processing = set()
http_session: aiohttp.ClientSession = None


async def get_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()
    return http_session


async def bot_api_call(method: str, data: aiohttp.FormData, timeout: int = 120):
    session = await get_session()
    async with session.post(f"{BOT_API_URL}/{method}", data=data, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        result = await resp.json()
        if not result.get("ok"):
            raise Exception(result.get("description", f"Bot API {method} failed"))
        return result


async def bot_api_send_video(chat_id, file_path, caption, reply_to, duration=None, width=None, height=None, thumb_path=None):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("video", open(file_path, "rb"), filename="video.mp4", content_type="video/mp4")
    if caption:
        data.add_field("caption", caption)
        data.add_field("parse_mode", "MarkdownV2")
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
    return await bot_api_call("sendVideo", data)


async def bot_api_send_audio(chat_id, file_path, caption, reply_to):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("audio", open(file_path, "rb"), filename="audio.mp3", content_type="audio/mpeg")
    if caption:
        data.add_field("caption", caption)
        data.add_field("parse_mode", "MarkdownV2")
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))
    return await bot_api_call("sendAudio", data, timeout=60)


async def bot_api_send_photo(chat_id, file_path, caption, reply_to):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("photo", open(file_path, "rb"), filename="photo.jpg", content_type="image/jpeg")
    if caption:
        data.add_field("caption", caption)
        data.add_field("parse_mode", "MarkdownV2")
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))
    return await bot_api_call("sendPhoto", data, timeout=60)


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
    data.add_field("media", json.dumps(media_list))
    return await bot_api_call("sendMediaGroup", data)


async def bot_api_send_message(chat_id, text, reply_to=None):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("text", text)
    if reply_to:
        data.add_field("reply_to_message_id", str(reply_to))
    return await bot_api_call("sendMessage", data, timeout=30)


async def bot_api_edit_message(chat_id, message_id, text):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("message_id", str(message_id))
    data.add_field("text", text)
    return await bot_api_call("editMessageText", data, timeout=30)


async def bot_api_delete_message(chat_id, message_id):
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("message_id", str(message_id))
    try:
        return await bot_api_call("deleteMessage", data, timeout=30)
    except Exception:
        pass


async def handle_update(update: dict):
    msg = update.get("message", {})
    text = msg.get("text", "")
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")

    if not chat_id or not text:
        return

    if text.startswith("/start"):
        await bot_api_send_message(
            chat_id,
            "\U0001f3ac Media Downloader\n\n"
            "Send a link from:\n"
            "\u2022 TikTok (videos + photos)\n"
            "\u2022 YouTube\n"
            "\u2022 X.com / Twitter (videos + photos)\n"
            "\u2022 Instagram (videos + photos)\n\n"
            "Works in groups \u2014 just drop a link.",
            reply_to=msg_id,
        )
        return

    urls = extract_urls(text)
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

            status_result = await bot_api_send_message(chat_id, f"{emoji} Downloading\u2026", reply_to=msg_id)
            status_id = status_result.get("result", {}).get("message_id")

            media, error = await download_media(url)

            if error:
                if status_id:
                    await bot_api_edit_message(chat_id, status_id, error)
                    asyncio.get_event_loop().call_later(
                        10, lambda sid=status_id: asyncio.ensure_future(bot_api_delete_message(chat_id, sid)))
                continue

            try:
                if media.media_type == "photos" and media.photo_paths:
                    if status_id:
                        await bot_api_edit_message(chat_id, status_id, "\u2b06\ufe0f Uploading\u2026")

                    caption = f"{emoji} {escape_md(media.title)}"
                    if len(media.photo_paths) == 1:
                        await bot_api_send_photo(chat_id, media.photo_paths[0], caption, msg_id)
                    else:
                        await bot_api_send_media_group(chat_id, media.photo_paths, caption, msg_id)

                    if media.audio_path:
                        await bot_api_send_audio(chat_id, media.audio_path, f"\U0001f3b5 {escape_md(media.title)}", msg_id)

                    if status_id:
                        await bot_api_delete_message(chat_id, status_id)

                else:
                    if status_id:
                        await bot_api_edit_message(chat_id, status_id, "\u2b06\ufe0f Uploading\u2026")

                    size_mb = media.file_size / 1024 / 1024
                    caption = f"{emoji} {escape_md(media.title)}\n{escape_md(f'{size_mb:.1f} MB')}"
                    if len(caption) > 1024:
                        caption = caption[:1021] + "\u2026"

                    await bot_api_send_video(
                        chat_id, media.file_path, caption, msg_id,
                        duration=media.duration, width=media.width, height=media.height,
                        thumb_path=media.thumbnail_path)
                    if status_id:
                        await bot_api_delete_message(chat_id, status_id)

            except Exception as e:
                logger.error("Upload error: %s", e)
                if status_id:
                    await bot_api_edit_message(chat_id, status_id, f"\u274c Upload failed: {e}")
            finally:
                if media.file_path:
                    cleanup_media(media.file_path)

        finally:
            processing.discard(url_hash)


async def polling_loop():
    offset = 0
    session = await get_session()
    logger.info("Bot polling started")

    while True:
        try:
            url = f"{BOT_API_URL}/getUpdates?offset={offset}&timeout=30"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                data = await resp.json()

            if not data.get("ok"):
                logger.error("getUpdates error: %s", data)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                asyncio.create_task(handle_update(update))

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error("Polling error: %s", e)
            await asyncio.sleep(5)


async def cleanup_loop():
    while True:
        await asyncio.sleep(300)
        await cleanup_old_files()


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

    logger.info("Bot starting (Bot API only, 50 MB limit)")

    asyncio.create_task(cleanup_loop())
    await polling_loop()


if __name__ == "__main__":
    asyncio.run(main())
