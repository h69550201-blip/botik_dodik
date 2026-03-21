import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from downloader import extract_urls, download_video, cleanup

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


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hey! Send me a link from TikTok, YouTube, Instagram, or X/Twitter "
        "and I'll download the video for you."
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    urls = extract_urls(update.message.text)
    if not urls:
        return

    for url in urls[:3]:
        status = await update.message.reply_text(
            "\u2b07\ufe0f Downloading\u2026",
            reply_to_message_id=update.message.message_id,
        )

        path = None
        try:
            result = download_video(url)
            info = await result
            path = info["path"]

            emoji = PLATFORM_EMOJI.get(info["platform"], "\U0001f3ac")
            caption_parts = []
            if info["title"]:
                caption_parts.append(info["title"])
            caption_parts.append(
                f"{emoji} {info['platform'].capitalize()} "
                f"| {info['size'] / 1024 / 1024:.1f} MB"
            )
            caption = "\n".join(caption_parts)
            if len(caption) > 1024:
                caption = caption[:1021] + "\u2026"

            with open(path, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=caption,
                    reply_to_message_id=update.message.message_id,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                    supports_streaming=True,
                )

            await status.delete()

        except ValueError as e:
            await status.edit_text(f"\u274c {e}")
        except Exception as e:
            logger.exception("Failed to download %s", url)
            await status.edit_text(
                f"\u274c Failed to download video.\n<code>{type(e).__name__}: {e}</code>",
                parse_mode="HTML",
            )
        finally:
            if path:
                cleanup(path)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

    app = (
        ApplicationBuilder()
        .token(token)
        .read_timeout(120)
        .write_timeout(120)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot starting (polling mode)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
