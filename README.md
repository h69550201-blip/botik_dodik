# botik_dodik

Telegram bot that downloads videos from **TikTok**, **YouTube**, **Instagram**, and **X/Twitter**. Drop a link in any chat — get the video back. Uploads up to **2 GB** via MTProto (Pyrogram).

## Setup

### 1. Get API credentials
- Go to [my.telegram.org](https://my.telegram.org) → API development tools
- Create an app → get your `API_ID` and `API_HASH`

### 2. Create the bot
- Message [@BotFather](https://t.me/BotFather) on Telegram
- `/newbot` → pick a name → get your `TELEGRAM_BOT_TOKEN`
- `/setprivacy` → select your bot → **Disable** (so it can read messages in groups)

### 3. Deploy on Railway
1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select this repo
4. Add environment variables:
   - `TELEGRAM_BOT_TOKEN` = token from BotFather
   - `API_ID` = number from my.telegram.org
   - `API_HASH` = hash from my.telegram.org
5. Deploy — Railway builds the Dockerfile automatically

### 4. Add bot to a group
- Add the bot to your Telegram group
- Make sure it has permission to read messages and send media

## How it works
1. Someone sends a message with a link from TikTok / YouTube / Instagram / X
2. Bot detects the URL, downloads the video via `yt-dlp`
3. Uploads the video via Pyrogram (MTProto) — up to **2 GB**
4. Shows upload progress bar for large files

## Supported platforms
| Platform | Example URLs |
|----------|-------------|
| TikTok | `tiktok.com/...`, `vm.tiktok.com/...` |
| YouTube | `youtube.com/watch?v=...`, `youtu.be/...`, `youtube.com/shorts/...` |
| Instagram | `instagram.com/reel/...`, `instagram.com/p/...` |
| X/Twitter | `x.com/.../status/...`, `twitter.com/.../status/...` |

## Local dev
```bash
export TELEGRAM_BOT_TOKEN=your_token
export API_ID=12345
export API_HASH=your_hash
pip install -r requirements.txt
python bot.py
```

## Cookies (for Instagram / age-restricted content)

Instagram requires login. To make it work:

1. Install a browser extension like [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Log into Instagram in your browser
3. Export cookies as `cookies.txt` (Netscape format)
4. Base64-encode it: `base64 -w0 cookies.txt`
5. Set the result as `COOKIES_BASE64` env var in Railway

This also helps with age-restricted YouTube videos and any other site that needs login.

## Environment variables
| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Token from BotFather |
| `API_ID` | Yes | App ID from my.telegram.org |
| `API_HASH` | Yes | App hash from my.telegram.org |
| `COOKIES_BASE64` | No | Base64-encoded cookies.txt for Instagram etc. |
