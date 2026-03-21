import os
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction

from downloader import extract_urls, download_video, cleanup, detect_platform, URL_PATTERN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PLATFORM_EMOJI = {
    "tiktok": "\U0001f3b5",
    "youtube": "\u25b6\ufe0f",
    "instagram": "\U0001f4f7",
    "twitter": "\U0001f426",
    "unknown": "\U0001f3ac",
}

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

app = Client(
    "botik_dodik",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
)


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
        "Hey! Send me a link from TikTok, YouTube, Instagram, or X/Twitter "
        "and I\u2019ll download the video for you.\n\n"
        "Works in groups too \u2014 just drop a link. Supports up to **2 GB** uploads."
    )


@app.on_message(filters.regex(URL_PATTERN))
async def handle_message(_client: Client, message: Message):
    if not message.text:
        return

    urls = extract_urls(message.text)
    if not urls:
        return

    for url in urls[:3]:
        status = await message.reply_text(
            "\u2b07\ufe0f Downloading\u2026",
            quote=True,
        )

        path = None
        try:
            platform = detect_platform(url)
            if platform == "tiktok" and "/photo/" in url:
                await status.edit_text("\u274c This is a TikTok photo post, not a video.")
                continue

            await _client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)

            info = await download_video(url)
            path = info["path"]

            emoji = PLATFORM_EMOJI.get(info["platform"], "\U0001f3ac")
            caption_parts = []
            if info["title"]:
                caption_parts.append(info["title"])
            size_mb = info["size"] / 1024 / 1024
            if size_mb >= 1024:
                size_str = f"{size_mb / 1024:.2f} GB"
            else:
                size_str = f"{size_mb:.1f} MB"
            caption_parts.append(
                f"{emoji} {info['platform'].capitalize()} | {size_str}"
            )
            caption = "\n".join(caption_parts)
            if len(caption) > 1024:
                caption = caption[:1021] + "\u2026"

            is_large = info["size"] > 100 * 1024 * 1024

            if is_large:
                await status.edit_text("\u2b06\ufe0f Uploading\u2026")

            await message.reply_video(
                video=path,
                caption=caption,
                quote=True,
                supports_streaming=True,
                duration=int(info["duration"]) if info["duration"] else None,
                progress=_progress_callback(status) if is_large else None,
            )

            await status.delete()

        except ValueError as e:
            await status.edit_text(f"\u274c {e}")
        except Exception as e:
            logger.exception("Failed to download %s", url)
            err = str(e)
            platform = detect_platform(url)
            if platform == "instagram" and ("login" in err.lower() or "cookie" in err.lower()):
                msg = "\u274c Instagram requires login. Ask the bot admin to set up cookies."
            elif "Unsupported URL" in err:
                msg = "\u274c This link type is not supported (might be a photo or story)."
            elif "format" in err.lower() and "not available" in err.lower():
                msg = "\u274c No downloadable video format found for this link."
            elif "Sign in" in err or "confirm your age" in err:
                msg = "\u274c This video is age-restricted and requires login."
            else:
                msg = f"\u274c Failed to download video.\n`{type(e).__name__}: {e}`"
            await status.edit_text(msg)
        finally:
            if path:
                cleanup(path)


if __name__ == "__main__":
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        raise RuntimeError(
            "Set API_ID, API_HASH, and TELEGRAM_BOT_TOKEN environment variables"
        )
    logger.info("Bot starting (Pyrogram MTProto, up to 2 GB uploads)")
    app.run()
