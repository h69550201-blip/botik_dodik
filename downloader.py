import asyncio
import os
import re
import uuid
import json
import shutil
import base64
import logging
import aiohttp
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("/tmp/botik_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

COOKIES_DIR = Path("/tmp/cookies")
COOKIES_DIR.mkdir(exist_ok=True)

TELEGRAM_MAX_SIZE = 2 * 1024 * 1024 * 1024

PLATFORM_COOKIES = {
    "tiktok": COOKIES_DIR / "tiktok_cookies.txt",
    "youtube": COOKIES_DIR / "youtube_cookies.txt",
    "twitter": COOKIES_DIR / "twitter_cookies.txt",
    "instagram": COOKIES_DIR / "instagram_cookies.txt",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".ts"}

TIKTOK_PATTERNS = [
    r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/[@\w./]+",
    r"(https?://)?(www\.)?tiktok\.com/@[\w.]+/video/\d+",
    r"(https?://)?(www\.)?tiktok\.com/@[\w.]+/photo/\d+",
]
YOUTUBE_PATTERNS = [
    r"(https?://)?(www\.)?youtube\.com/shorts/[\w-]+",
    r"(https?://)?(www\.)?youtu\.be/[\w-]+",
    r"(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+",
]
TWITTER_PATTERNS = [
    r"(https?://)?(www\.)?(twitter\.com|x\.com)/\w+/status/\d+",
]
INSTAGRAM_PATTERNS = [
    r"(https?://)?(www\.)?instagram\.com/reel/[\w-]+",
    r"(https?://)?(www\.)?instagram\.com/reels/[\w-]+",
    r"(https?://)?(www\.)?instagram\.com/p/[\w-]+",
    r"(https?://)?(www\.)?instagram\.com/tv/[\w-]+",
]

URL_PATTERN = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.)?"
    r"(?:tiktok\.com|youtube\.com|youtu\.be|instagram\.com|twitter\.com|x\.com)"
    r"/\S+"
)


@dataclass
class MediaInfo:
    media_type: str
    platform: str
    title: str = "Media"
    file_path: Optional[str] = None
    duration: int = 0
    file_size: int = 0
    width: int = 0
    height: int = 0
    thumbnail_path: Optional[str] = None
    photo_paths: list = field(default_factory=list)
    audio_path: Optional[str] = None


def setup_cookies():
    for platform in PLATFORM_COOKIES:
        env_key = f"COOKIES_{platform.upper()}_BASE64"
        raw = os.environ.get(env_key, "")
        if raw:
            PLATFORM_COOKIES[platform].write_bytes(base64.b64decode(raw))
            logger.info("Cookies written for %s from %s", platform, env_key)

    raw = os.environ.get("COOKIES_BASE64", "")
    if raw:
        PLATFORM_COOKIES["instagram"].write_bytes(base64.b64decode(raw))
        logger.info("Cookies written for instagram from COOKIES_BASE64")


setup_cookies()


def extract_urls(text: str) -> list[str]:
    all_patterns = TIKTOK_PATTERNS + YOUTUBE_PATTERNS + TWITTER_PATTERNS + INSTAGRAM_PATTERNS
    urls = []
    for pattern in all_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            urls.append(match.group(0))
    return list(dict.fromkeys(urls))


def get_platform(url: str) -> Optional[str]:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    if "instagram.com" in u:
        return "instagram"
    return None


def get_cookie_path(platform: str) -> Optional[Path]:
    p = PLATFORM_COOKIES.get(platform)
    if p and p.exists():
        return p
    return None


async def get_video_metadata(video_path: str) -> Tuple[int, int, int]:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", video_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = json.loads(stdout.decode())
        duration = int(float(data.get("format", {}).get("duration", 0)))
        width, height = 0, 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width", 0)
                height = stream.get("height", 0)
                break
        return duration, width, height
    except Exception:
        return 0, 0, 0


async def generate_thumbnail(video_path: str, output_path: str) -> bool:
    try:
        cmd = ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01",
               "-vframes", "1", "-vf", "scale=320:-1", output_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.communicate(), timeout=15)
        return Path(output_path).exists()
    except Exception:
        return False


async def _twitter_get_media(url: str) -> Optional[dict]:
    match = re.search(r"(?:twitter\.com|x\.com)/(\w+)/status/(\d+)", url)
    if not match:
        return None
    username, tweet_id = match.group(1), match.group(2)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            api_url = f"https://api.fxtwitter.com/{username}/status/{tweet_id}"
            async with session.get(api_url, headers={"User-Agent": "BotikDodik/1.0"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        tweet = data.get("tweet", {})
        if not tweet:
            return None
        title = (tweet.get("text") or "Tweet")[:100]
        media = tweet.get("media", {})
        videos = media.get("videos") or []
        photos = media.get("photos") or []
        if videos:
            return {"type": "video", "title": title}
        if photos:
            image_urls = [p["url"] for p in photos if p.get("url")]
            if image_urls:
                return {"type": "photos", "urls": image_urls, "title": title}
        return None
    except Exception as e:
        logger.error("fxtwitter error: %s", e)
        return None


async def probe_content(url: str, platform: str) -> Optional[dict]:
    if platform == "twitter":
        return await _twitter_get_media(url)

    cmd = ["yt-dlp", "-J", "--no-download", "--no-warnings"]
    cookie_path = get_cookie_path(platform)
    if cookie_path:
        cmd.extend(["--cookies", str(cookie_path)])
    if platform == "tiktok":
        cmd.extend(["--add-header", "User-Agent:Mozilla/5.0"])
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return None
        raw = stdout.decode().strip()
        if not raw:
            return None
        data = json.loads(raw)
        title = (data.get("title") or data.get("description") or "Media")[:100]
        entries = data.get("entries") or [data]
        entries = [e for e in entries if e]
        if not entries:
            return None
        image_urls = []
        audio_url = None
        has_video = False
        for entry in entries:
            formats = entry.get("formats") or []
            if any((f.get("vcodec") or "none") != "none" for f in formats):
                has_video = True
                break
            entry_ext = (entry.get("ext") or "").lower()
            entry_url = entry.get("url") or ""
            if entry_ext in ("jpg", "jpeg", "png", "webp") and entry_url:
                image_urls.append(entry_url)
                continue
            for f in sorted(formats, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True):
                f_ext = (f.get("ext") or "").lower()
                f_url = f.get("url") or ""
                if f_ext in ("jpg", "jpeg", "png", "webp") and f_url:
                    image_urls.append(f_url)
                    break
            if not audio_url:
                for f in formats:
                    acodec = f.get("acodec") or "none"
                    vcodec = f.get("vcodec") or "none"
                    if acodec != "none" and vcodec == "none" and f.get("url"):
                        audio_url = f["url"]
                        break
        if not audio_url:
            for entry in entries:
                for f in (entry.get("formats") or []):
                    acodec = f.get("acodec") or "none"
                    if acodec != "none" and f.get("url"):
                        audio_url = f["url"]
                        break
                if audio_url:
                    break
        if has_video:
            return {"type": "video", "title": title}
        if image_urls:
            return {"type": "photos", "urls": list(dict.fromkeys(image_urls)), "title": title, "audio_url": audio_url}
        return None
    except Exception as e:
        logger.error("Probe error: %s", e)
        return None


async def _download_audio(audio_url: str, output_dir: Path) -> Optional[str]:
    if not audio_url:
        return None
    audio_path = output_dir / "audio.mp3"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(audio_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()
                if len(content) < 1024:
                    return None
                raw_path = output_dir / "audio_raw"
                raw_path.write_bytes(content)
        cmd = ["ffmpeg", "-y", "-i", str(raw_path), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(audio_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.communicate(), timeout=30)
        raw_path.unlink(missing_ok=True)
        if audio_path.exists() and audio_path.stat().st_size > 0:
            return str(audio_path)
        return None
    except Exception as e:
        logger.error("Audio download error: %s", e)
        return None


async def _download_photos(image_urls: list, title: str, platform: str, output_dir: Path, audio_url: str = None) -> Tuple[Optional[MediaInfo], Optional[str]]:
    if not image_urls:
        return None, "No photos found"
    photo_paths = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    timeout = aiohttp.ClientTimeout(total=30)

    photo_coro = _download_photos_only(image_urls, output_dir, headers, timeout)
    audio_coro = _download_audio(audio_url, output_dir)
    photo_paths, audio_path = await asyncio.gather(photo_coro, audio_coro)

    if not photo_paths:
        return None, "Failed to download photos"
    return MediaInfo(
        media_type="photos", platform=platform,
        title=title[:100] if title else "Photos",
        file_path=photo_paths[0],
        file_size=sum(Path(p).stat().st_size for p in photo_paths),
        photo_paths=photo_paths,
        audio_path=audio_path,
    ), None


async def _download_photos_only(image_urls, output_dir, headers, timeout):
    photo_paths = []
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        for i, url in enumerate(image_urls[:10]):
            if not url:
                continue
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.read()
                    if len(content) < 1024:
                        continue
                    ct = (resp.headers.get("Content-Type") or "").lower()
                    ext = ".png" if "png" in ct else ".webp" if "webp" in ct else ".jpg"
                    photo_path = output_dir / f"photo_{i:03d}{ext}"
                    photo_path.write_bytes(content)
                    photo_paths.append(str(photo_path))
            except Exception as e:
                logger.error("Photo download error: %s", e)
    return photo_paths


async def _gallery_dl_download(url: str, platform: str, output_dir: Path) -> Optional[Tuple[MediaInfo, None]]:
    cmd = ["gallery-dl", "--no-mtime", "--dest", str(output_dir)]
    cookie_path = get_cookie_path(platform)
    if cookie_path:
        cmd.extend(["--cookies", str(cookie_path)])
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            return None
        images, videos = [], []
        for root, dirs, files in os.walk(str(output_dir)):
            for f in files:
                fpath = os.path.join(root, f)
                if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                    images.append(fpath)
                elif Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(fpath)
        if images and not videos:
            photo_paths = sorted(images)[:10]
            return MediaInfo(
                media_type="photos", platform=platform, title="Photos",
                file_path=photo_paths[0],
                file_size=sum(Path(p).stat().st_size for p in photo_paths),
                photo_paths=photo_paths,
            ), None
        if videos:
            return MediaInfo(
                media_type="video", platform=platform, title="Video",
                file_path=videos[0],
                file_size=Path(videos[0]).stat().st_size,
            ), None
        return None
    except Exception as e:
        logger.error("gallery-dl error: %s", e)
        return None


async def _tiktok_api_download(url: str, output_dir: Path) -> Optional[Tuple[MediaInfo, None]]:
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://www.tikwm.com/api/",
                params={"url": url, "hd": 1},
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            if data.get("code") != 0:
                return None

            vdata = data.get("data", {})
            title = (vdata.get("title") or "TikTok")[:100]

            images = vdata.get("images")
            if images:
                photo_paths = []
                audio_url = vdata.get("music")
                for i, img_url in enumerate(images[:10]):
                    try:
                        async with session.get(img_url) as img_resp:
                            if img_resp.status != 200:
                                continue
                            content = await img_resp.read()
                            photo_path = output_dir / f"photo_{i:03d}.jpg"
                            photo_path.write_bytes(content)
                            photo_paths.append(str(photo_path))
                    except Exception:
                        continue
                if not photo_paths:
                    return None
                audio_path = None
                if audio_url:
                    audio_path = await _download_audio(audio_url, output_dir)
                return MediaInfo(
                    media_type="photos", platform="tiktok", title=title,
                    file_path=photo_paths[0],
                    file_size=sum(Path(p).stat().st_size for p in photo_paths),
                    photo_paths=photo_paths, audio_path=audio_path,
                ), None

            video_url = vdata.get("hdplay") or vdata.get("play")
            if not video_url:
                return None

            video_path = output_dir / "video.mp4"
            async with session.get(video_url) as vid_resp:
                if vid_resp.status != 200:
                    return None
                with open(video_path, "wb") as f:
                    async for chunk in vid_resp.content.iter_chunked(65536):
                        f.write(chunk)

            if not video_path.exists() or video_path.stat().st_size < 1024:
                return None

            duration, width, height = await get_video_metadata(str(video_path))
            thumb_path = str(output_dir / "thumb.jpg")
            await generate_thumbnail(str(video_path), thumb_path)

            return MediaInfo(
                media_type="video", platform="tiktok", title=title,
                file_path=str(video_path), duration=duration,
                file_size=video_path.stat().st_size,
                width=width, height=height,
                thumbnail_path=thumb_path if Path(thumb_path).exists() else None,
            ), None

    except Exception as e:
        logger.error("TikTok API error: %s", e)
        return None


async def _youtube_retry_download(url: str, output_dir: Path) -> Optional[Tuple[MediaInfo, None]]:
    clients = ["android", "ios", "mweb"]
    for client in clients:
        try:
            temp_path = str(output_dir / f"retry.%(ext)s")
            cmd = [
                "yt-dlp", "--no-playlist", "--no-warnings",
                "-o", temp_path, "--socket-timeout", "30",
                "-f", "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
                "--merge-output-format", "mp4",
                "--extractor-args", f"youtube:player_client={client}",
                url,
            ]
            cookie_path = get_cookie_path("youtube")
            if cookie_path:
                cmd.insert(-1, "--cookies")
                cmd.insert(-1, str(cookie_path))

            logger.info("YouTube retry with client=%s: %s", client, url)
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                continue

            downloaded = list(output_dir.glob("retry.*"))
            if not downloaded:
                continue

            temp_file = downloaded[0]
            final_path = str(output_dir / "video.mp4")
            if temp_file.suffix.lower() != ".mp4":
                rp = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", str(temp_file), "-c", "copy", final_path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await asyncio.wait_for(rp.communicate(), timeout=60)
                if Path(final_path).exists() and Path(final_path).stat().st_size > 0:
                    temp_file.unlink()
                else:
                    shutil.move(str(temp_file), final_path)
            else:
                shutil.move(str(temp_file), final_path)

            if not Path(final_path).exists():
                continue

            file_size = Path(final_path).stat().st_size
            if file_size > TELEGRAM_MAX_SIZE:
                Path(final_path).unlink()
                continue

            duration, width, height = await get_video_metadata(final_path)
            thumb_path = str(output_dir / "thumb.jpg")
            await generate_thumbnail(final_path, thumb_path)

            title = "Video"
            try:
                tp = await asyncio.create_subprocess_exec(
                    "yt-dlp", "--get-title", "--no-warnings", url,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                tout, _ = await asyncio.wait_for(tp.communicate(), timeout=10)
                title = tout.decode().strip()[:100] if tout else "Video"
            except Exception:
                pass

            return MediaInfo(
                media_type="video", platform="youtube", file_path=final_path,
                title=title, duration=duration, file_size=file_size,
                width=width, height=height,
                thumbnail_path=thumb_path if Path(thumb_path).exists() else None,
            ), None

        except Exception as e:
            logger.error("YouTube retry (%s) error: %s", client, e)
            continue

    return None


def _parse_error(error_msg: str, platform: str) -> str:
    e = error_msg.lower()
    if "private" in e:
        return "\u274c This content is private"
    if "unavailable" in e or "not available" in e:
        return "\u274c Content is unavailable"
    if "removed" in e or "deleted" in e:
        return "\u274c Content was deleted"
    if "age" in e or "sign in" in e or "login" in e:
        return f"\u274c Login required \u2014 use /setcookies {platform}"
    if "copyright" in e:
        return "\u274c Blocked due to copyright"
    if "geo" in e or "country" in e or "region" in e:
        return "\u274c Not available in this region"
    if "not found" in e or "404" in e or "exist" in e:
        return "\u274c Content does not exist"
    if "rate" in e or "too many" in e:
        return "\u274c Rate limited, try again later"
    if "format" in e and "available" in e:
        return "\u274c No downloadable format found"
    if "timed out" in e or "timeout" in e:
        return "\u274c Connection timed out"
    if "live" in e:
        return "\u274c Cannot download live streams"
    return "\u274c Download failed"


async def download_media(url: str) -> Tuple[Optional[MediaInfo], Optional[str]]:
    platform = get_platform(url)
    if not platform:
        return None, "\u274c Unsupported URL"

    vid = uuid.uuid4().hex[:8]
    output_dir = DOWNLOAD_DIR / vid
    output_dir.mkdir(exist_ok=True)
    temp_path = str(output_dir / "temp.%(ext)s")
    final_path = str(output_dir / "video.mp4")
    thumb_path = str(output_dir / "thumb.jpg")

    if platform != "youtube":
        if platform == "tiktok":
            try:
                api_result = await _tiktok_api_download(url, output_dir)
                if api_result:
                    return api_result
                output_dir.mkdir(exist_ok=True)
            except Exception:
                output_dir.mkdir(exist_ok=True)

        if platform == "tiktok" and "/photo/" in url:
            try:
                result = await _gallery_dl_download(url, platform, output_dir)
                if result:
                    return result
                output_dir.mkdir(exist_ok=True)
            except Exception:
                output_dir.mkdir(exist_ok=True)

        try:
            content = await probe_content(url, platform)
            if content and content.get("type") == "photos" and content.get("urls"):
                result = await _download_photos(
                    content["urls"], content.get("title", "Photos"), platform, output_dir,
                    audio_url=content.get("audio_url"))
                if result[0] is not None:
                    return result
                output_dir.mkdir(exist_ok=True)
        except Exception:
            output_dir.mkdir(exist_ok=True)

    cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "-o", temp_path, "--socket-timeout", "30"]

    cookie_path = get_cookie_path(platform)
    if cookie_path:
        cmd.extend(["--cookies", str(cookie_path)])

    if platform == "tiktok":
        cmd.extend(["-f", "bestvideo*+bestaudio/best"])
        cmd.extend(["--add-header", "User-Agent:Mozilla/5.0"])
        cmd.extend(["--merge-output-format", "mp4"])
    elif platform == "twitter":
        cmd.extend(["-f", "best[height<=720]/best[height<=480]/best"])
        cmd.extend([
            "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--extractor-args", "twitter:api=syndication",
        ])
    elif platform == "instagram":
        cmd.extend(["-f", "best"])
    elif platform == "youtube":
        cmd.extend(["-f", "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"])
        cmd.extend(["--merge-output-format", "mp4"])
    else:
        cmd.extend(["-f", "bv*+ba/b"])

    cmd.append(url)

    try:
        logger.info("Downloading: %s", url)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            error_msg = (stderr.decode() if stderr else "") + (stdout.decode() if stdout else "")
            logger.error("yt-dlp error: %s", error_msg[:500])

            if platform in ("twitter", "instagram", "tiktok"):
                output_dir.mkdir(exist_ok=True)
                gallery_result = await _gallery_dl_download(url, platform, output_dir)
                if gallery_result:
                    return gallery_result

            if platform == "tiktok":
                output_dir.mkdir(exist_ok=True)
                api_result = await _tiktok_api_download(url, output_dir)
                if api_result:
                    return api_result

            if platform == "youtube":
                output_dir.mkdir(exist_ok=True)
                yt_result = await _youtube_retry_download(url, output_dir)
                if yt_result:
                    return yt_result

            shutil.rmtree(output_dir, ignore_errors=True)
            return None, _parse_error(error_msg, platform)

        downloaded = list(output_dir.glob("temp.*"))
        if not downloaded:
            if platform in ("twitter", "instagram", "tiktok"):
                gallery_result = await _gallery_dl_download(url, platform, output_dir)
                if gallery_result:
                    return gallery_result
            shutil.rmtree(output_dir, ignore_errors=True)
            return None, "\u274c No media found"

        images = [f for f in downloaded if f.suffix.lower() in IMAGE_EXTENSIONS]
        videos = [f for f in downloaded if f.suffix.lower() not in IMAGE_EXTENSIONS]

        if images and not videos:
            photo_paths = [str(p) for p in sorted(images)]
            return MediaInfo(
                media_type="photos", platform=platform, title="Photos",
                file_path=photo_paths[0],
                file_size=sum(p.stat().st_size for p in images),
                photo_paths=photo_paths,
            ), None

        temp_file = videos[0] if videos else downloaded[0]

        if temp_file.suffix.lower() != ".mp4":
            remux_cmd = ["ffmpeg", "-y", "-i", str(temp_file), "-c", "copy", final_path]
            rp = await asyncio.create_subprocess_exec(
                *remux_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await asyncio.wait_for(rp.communicate(), timeout=60)
            if Path(final_path).exists() and Path(final_path).stat().st_size > 0:
                temp_file.unlink()
            else:
                shutil.move(str(temp_file), final_path)
        else:
            shutil.move(str(temp_file), final_path)

        if not Path(final_path).exists():
            shutil.rmtree(output_dir, ignore_errors=True)
            return None, "\u274c Conversion failed"

        file_size = Path(final_path).stat().st_size
        if file_size > TELEGRAM_MAX_SIZE:
            shutil.rmtree(output_dir, ignore_errors=True)
            return None, f"\u274c Too large ({file_size // 1024 // 1024} MB). Limit is 2 GB"

        duration, width, height = await get_video_metadata(final_path)
        await generate_thumbnail(final_path, thumb_path)

        title = "Video"
        try:
            title_cmd = ["yt-dlp", "--get-title", "--no-warnings", url]
            if cookie_path:
                title_cmd.extend(["--cookies", str(cookie_path)])
            tp = await asyncio.create_subprocess_exec(
                *title_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            tout, _ = await asyncio.wait_for(tp.communicate(), timeout=10)
            title = tout.decode().strip()[:100] if tout else "Video"
        except Exception:
            pass

        return MediaInfo(
            media_type="video", platform=platform, file_path=final_path,
            title=title, duration=duration, file_size=file_size,
            width=width, height=height,
            thumbnail_path=thumb_path if Path(thumb_path).exists() else None,
        ), None

    except asyncio.TimeoutError:
        shutil.rmtree(output_dir, ignore_errors=True)
        return None, "\u274c Download timed out"
    except Exception as e:
        logger.error("Download error: %s", e)
        shutil.rmtree(output_dir, ignore_errors=True)
        return None, "\u274c Download failed"


def cleanup_media(file_path: str):
    try:
        shutil.rmtree(Path(file_path).parent, ignore_errors=True)
    except Exception:
        pass


async def cleanup_old_files():
    import time
    try:
        for item in DOWNLOAD_DIR.iterdir():
            if item.is_dir() and time.time() - item.stat().st_mtime > 300:
                shutil.rmtree(item, ignore_errors=True)
    except Exception:
        pass
