import os
import re
import uuid
import logging
import asyncio
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("/tmp/botik_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

TELEGRAM_MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB (Pyrogram MTProto limit)

PLATFORM_PATTERNS = {
    "tiktok": re.compile(
        r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+"
    ),
    "youtube": re.compile(
        r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch|shorts|live)|youtu\.be/)\S+"
    ),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/\S+"
    ),
    "twitter": re.compile(
        r"https?://(?:www\.)?(?:twitter\.com|x\.com)/\S+/status/\S+"
    ),
}

URL_PATTERN = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.)?"
    r"(?:tiktok\.com|youtube\.com|youtu\.be|instagram\.com|twitter\.com|x\.com)"
    r"/\S+"
)


def extract_urls(text: str) -> list[str]:
    return URL_PATTERN.findall(text)


def detect_platform(url: str) -> str | None:
    for platform, pattern in PLATFORM_PATTERNS.items():
        if pattern.match(url):
            return platform
    return None


def _ydl_opts(out_path: str) -> dict:
    return {
        "outtmpl": out_path,
        "format": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio"
            "/best[ext=mp4]"
            "/best"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ],
    }


async def download_video(url: str) -> dict:
    file_id = uuid.uuid4().hex[:12]
    out_path = str(DOWNLOAD_DIR / f"{file_id}.%(ext)s")
    final_path = str(DOWNLOAD_DIR / f"{file_id}.mp4")

    platform = detect_platform(url) or "unknown"
    logger.info("Downloading from %s: %s", platform, url)

    opts = _ydl_opts(out_path)

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _sync_download, url, opts)

    found = None
    for f in DOWNLOAD_DIR.glob(f"{file_id}.*"):
        if f.suffix != ".part":
            found = f
            break

    if found is None:
        raise FileNotFoundError("Download produced no file")

    if str(found) != final_path:
        found = found.rename(final_path)

    size = os.path.getsize(final_path)
    if size > TELEGRAM_MAX_SIZE:
        os.remove(final_path)
        raise ValueError(
            f"Video too large ({size / 1024 / 1024:.1f} MB). "
            f"Telegram limit is 2 GB."
        )

    title = info.get("title", "")[:200] if info else ""
    duration = info.get("duration") if info else None

    return {
        "path": final_path,
        "title": title,
        "duration": duration,
        "platform": platform,
        "size": size,
    }


def _sync_download(url: str, opts: dict) -> dict | None:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
