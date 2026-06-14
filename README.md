# Bicycle Tour Blog Automation Bot

Telegram bot that automates daily blog entry creation from voice recordings, photos, and GPS route data.

## Architecture

```
User (Telegram)
  ↓
Telegram Bot (@KaiKiste_bot)
  ↓
Flask Backend (Python)
  ├─ Voice → Transcription (OpenAI Whisper)
  ├─ GPX → Route Stats (gpxpy)
  └─ Text → Rewrite (Claude API)
  ↓
HTML Preview (in Telegram)
  ↓
User Approval (Telegram Button)
  ↓
Astro Build + Deploy (IONOS)
```

## Setup

### Prerequisites
- Docker + Docker Compose
- Telegram bot token (from @BotFather)
- OpenAI API key (Whisper)
- Anthropic API key (Claude)
- Astro repo at `/opt/astro`
- NAS mounted at `/mnt/nas/tour-inputs`

### 1. Clone and Configure

```bash
git clone <repo> /opt/astro-tour-bot
cd /opt/astro-tour-bot

# Create .env from template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Set Up NAS Directory

```bash
sudo mkdir -p /mnt/nas/tour-inputs/{pending,processed}
sudo chmod 755 /mnt/nas/tour-inputs
```

### 3. Deploy Container

```bash
cd /opt/astro-tour-bot
docker-compose up -d
```

### 4. Configure Telegram Webhook

Set webhook on your Telegram bot to point to your server:

```bash
curl -X POST https://api.telegram.org/bot{TOKEN}/setWebhook \
  -d "url=https://jurtin.de/tour-bot/webhook"
```

## Usage

### User Workflow

1. **Open Telegram** → Search for `@KaiKiste_bot`
2. **Send:**
   - 🎤 Voice message (describe your day)
   - 📸 Photos (your photos)
   - 🗺️ GPX file (export from Garmin)
3. **Type:** `/done`
4. **Receive:** Blog preview with [✅ Approve] button
5. **Click:** Approve → Blog published!

### Admin Endpoints

```bash
# Health check
curl http://localhost:5000/tour-bot/status

# List jobs
curl http://localhost:5000/tour-bot/jobs
```

## Files

```
/opt/astro-tour-bot/
├── app.py                    # Flask app + webhook
├── database.py               # SQLite schema + queries
├── requirements.txt          # Python dependencies
├── docker-compose.yml        # Container config
├── Dockerfile                # Image definition
└── processors/
    ├── telegram_handler.py   # Telegram message/callback handling
    ├── blog_processor.py     # Transcription + rewriting
    └── blog_publisher.py     # Git commit + deploy
```

## Processing Pipeline

### Step 1: Telegram Webhook
- Receives voice/photos/GPX files
- Stores in `/mnt/nas/tour-inputs/pending/`
- Queues for processing

### Step 2: Transcription
- Voice file → OpenAI Whisper API
- Returns German text

### Step 3: Route Parsing
- GPX file → gpxpy library
- Extracts: distance, elevation, start/end points

### Step 4: Rewrite with Claude
- Raw transcription + route stats
- Claude rewrites in user's voice (Belgium tour style)
- Matches tone: conversational, personal, humorous, reflective

### Step 5: Preview
- Generates HTML preview
- Sends to user via Telegram with [Approve] button

### Step 6: Auto-Publish (on approval)
1. Create markdown blog file
2. Copy photos to `/public/images/blog/YYYY/MM/DD/`
3. `git commit` with message
4. `npm run build` (Astro)
5. `bash /tmp/sftp_upload.sh` (deploy to IONOS)

## Troubleshooting

### Logs
```bash
docker logs -f tour-bot
```

### Database
```bash
# Check SQLite
sqlite3 /mnt/nas/tour-inputs/tour-bot.db ".tables"
```

### Reset
```bash
docker-compose down
rm /mnt/nas/tour-inputs/tour-bot.db
docker-compose up -d
```

## Next Steps

1. **Live tracking page** — real-time GPS map (separate service)
2. **Blog connection** — link live map to blog entries
3. **Image optimization** — resize/compress photos automatically
4. **Stats display** — embed elevation/speed charts

## Notes

- All API keys stored in `.env` (never in git)
- Files stored on NAS (persistent, backed up)
- SQLite for job tracking (one file, portable)
- Telegram approval is safer than auto-publish
- Voice rewriting preserves user's authentic voice
