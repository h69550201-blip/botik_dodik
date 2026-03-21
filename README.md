# botik_dodik

Telegram bot that downloads videos from **TikTok**, **YouTube**, **Instagram**, and **X/Twitter**. Drop a link in any chat — get the video back.

## Setup

### 1. Create the bot
- Message [@BotFather](https://t.me/BotFather) on Telegram
- `/newbot` → pick a name → get your `TELEGRAM_BOT_TOKEN`
- `/setprivacy` → select your bot → **Disable** (so it can read messages in groups)

### 2. Deploy on Railway
1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select this repo
4. Add environment variable: `TELEGRAM_BOT_TOKEN` = your token
5. Deploy — Railway will build the Dockerfile automatically

### 3. Add bot to a group
- Add the bot to your Telegram group
- Make sure it has permission to read messages and send media

## How it works
1. Someone sends a message with a link from TikTok / YouTube / Instagram / X
2. Bot detects the URL, downloads the video via `yt-dlp`
3. Sends the video back as a reply (up to 50 MB — Telegram limit)

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
pip install -r requirements.txt
python bot.py
```

## Environment variables
| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Token from BotFather |
