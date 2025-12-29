# AvatarTalk — YouTube RTMP Streamer

Small Python app that generates short language‑learning segments with OpenAI and streams them via AvatarTalk to a YouTube Live RTMP endpoint. Supports multiple languages. It can also read live chat, adapt the next topic accordingly, and post generated responses back to the live chat.

## Quick Start
- Requirements: Python 3.13, `uv`.
- Install deps: `uv sync`
- Set up YouTube OAuth2 credentials (see below).
- Create `.env` with your keys (see below).
- Start: `uv run main.py --background-url <BACKGROUND_URL> --language <LANGUAGE_CODE> <YOUTUBE_LIVE_ID>`

## YouTube Setup

### RTMP Streaming
- RTMP URL: use `rtmp://a.rtmp.youtube.com/live2` unless YouTube tells you otherwise.
- Stream key: in YouTube Studio → Go live → Stream → Stream key.

### YouTube Data API v3 (OAuth2)
This app uses OAuth2 authentication to read live chat comments and post responses back to chat. You'll need to create OAuth2 credentials in Google Cloud Console:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable "YouTube Data API v3" for your project
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Choose "Desktop app" as the application type
6. Download the JSON file and save it (e.g., as `gcp_youtube_oauth_key.json`)
7. Set `GOOGLE_CLIENT_SECRETS_PATH` in `.env` to point to this file
8. On first run, the app will open a browser window for OAuth2 authorization
9. You'll also need a YouTube API key (`YOUTUBE_API_KEY`) for certain read operations

## Configuration (.env)
Set these environment variables in a `.env` file next to `main.py`:

```bash
# OpenAI for content generation (required)
OPENAI_API_KEY=sk-...

# AvatarTalk RTMP gateway (API key required; URL optional)
AVATARTALK_API_KEY=...
# Optional: defaults to wss://api.avatartalk.ai
AVATARTALK_URL=wss://api.avatartalk.ai
# Avatar name as configured in your AvatarTalk account
AVATARTALK_AVATAR=...
# Spoken language (default: en)
AVATARTALK_LANGUAGE=en
# Model used for generation (default: gpt-4o-mini)
AVATARTALK_MODEL=gpt-4o-mini

# YouTube streaming (required to publish video)
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=...

# YouTube Data API v3 (required to read/post live chat)
YOUTUBE_API_KEY=...
# Path to OAuth2 credentials JSON file (required for chat posting)
GOOGLE_CLIENT_SECRETS_PATH=gcp_youtube_oauth_key.json

# Optional: set if you don't pass the video ID via CLI
YOUTUBE_LIVE_ID=<VIDEO_ID>

# Topics file (must exist). Defaults to topics.txt in this folder
AVATARTALK_TOPICS_FILE=topics.txt
```

## Run

### Manual Mode
- With explicit video ID: `uv run python main.py <VIDEO_ID>`
- Using env fallback: `YOUTUBE_LIVE_ID=<VIDEO_ID> uv run python main.py`
- Optional background image: add `--background-url <https-url>`
- Specify language: add `--language <code>` (default: `en`)
- Adjust logging: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL`
- Skip welcome messages: add `--skip-welcome` (useful when manually restarting)

The generated speaking segment is printed to stdout (handy for piping/testing). Operational logs go to stderr. Press Ctrl+C to stop gracefully.

**Note:** On first run, the app will open a browser window for OAuth2 authorization to access YouTube live chat. This is required for posting responses back to the chat.

### Infinite Restart Mode (Production)
For production use, we provide a bash script that automatically restarts the streamer if it crashes:

```bash
./run_streamer.sh <VIDEO_ID> <LANGUAGE> [BACKGROUND_URL]
```

**Examples:**
```bash
# Basic usage with English
./run_streamer.sh dQw4w9WgXcQ en

# With custom background
./run_streamer.sh dQw4w9WgXcQ es https://avatartalk.ai/images/backgrounds/gym_1.png

# French stream
./run_streamer.sh abc123 fr
```

**Features:**
- **Auto-restart**: Automatically restarts the streamer if it crashes
- **Smart welcome detection**: Automatically detects if welcome messages were already posted and skips them on restart
- **Crash protection**: Exits after 10 crashes to prevent infinite error loops
- **Colored output**: Easy-to-read status messages with color coding
- **Exit code handling**: Different behavior based on exit codes (normal exit, crash, config error, etc.)
- **Runtime tracking**: Shows how long each session ran before exit
- **Graceful shutdown**: Press Ctrl+C to stop the restart loop

**Exit Codes:**
- `0`: Normal exit → Restarts in 5 seconds
- `1`: Crash → Restarts in 10 seconds (or 30s if crash was very quick)
- `2`: Configuration error → Exits immediately (fix config and restart manually)
- `130`: User interrupt (Ctrl+C) → Exits gracefully

This script is recommended for production streams where you want the stream to continue even if there are temporary issues.

## Backgrounds

Here's the list of available backgrounds provided by AvatarTalk.ai:
- https://avatartalk.ai/images/backgrounds/feng_shui_1.png (default)
- https://avatartalk.ai/images/backgrounds/feng_shui_2.png
- https://avatartalk.ai/images/backgrounds/feng_shui_3.png
- https://avatartalk.ai/images/backgrounds/feng_shui_4.png
- https://avatartalk.ai/images/backgrounds/feng_shui_5.png
- https://avatartalk.ai/images/backgrounds/dance_hall_1.png
- https://avatartalk.ai/images/backgrounds/dance_hall_2.png
- https://avatartalk.ai/images/backgrounds/dance_hall_3.png
- https://avatartalk.ai/images/backgrounds/dance_hall_4.png
- https://avatartalk.ai/images/backgrounds/dance_hall_5.png
- https://avatartalk.ai/images/backgrounds/gym_1.png
- https://avatartalk.ai/images/backgrounds/gym_2.png
- https://avatartalk.ai/images/backgrounds/gym_3.png
- https://avatartalk.ai/images/backgrounds/gym_4.png
- https://avatartalk.ai/images/backgrounds/gym_5.png
- https://avatartalk.ai/images/backgrounds/kitchen_1.png
- https://avatartalk.ai/images/backgrounds/kitchen_2.png
- https://avatartalk.ai/images/backgrounds/kitchen_3.png
- https://avatartalk.ai/images/backgrounds/kitchen_4.png
- https://avatartalk.ai/images/backgrounds/kitchen_5.png
- https://avatartalk.ai/images/backgrounds/template_1.png
- https://avatartalk.ai/images/backgrounds/template_2.png
- https://avatartalk.ai/images/backgrounds/template_3.png
- https://avatartalk.ai/images/backgrounds/template_4.png
- https://avatartalk.ai/images/backgrounds/template_5.png
- https://avatartalk.ai/images/backgrounds/temple_1.png
- https://avatartalk.ai/images/backgrounds/temple_2.png
- https://avatartalk.ai/images/backgrounds/temple_3.png
- https://avatartalk.ai/images/backgrounds/temple_4.png
- https://avatartalk.ai/images/backgrounds/temple_5.png

## CLI Options
- `video_id` (positional, optional): YouTube Live video ID. Falls back to `YOUTUBE_LIVE_ID`.
- `--background-url`: HTTPS URL for a background image in the RTMP stream.
- `--language`: Language code for speech synthesis (default: `en`).
- `--log-level`: Logging verbosity (default: `INFO`).

## How It Works
- Reads recent YouTube Live chat messages (if available) via YouTube Data API v3.
- Chooses a topic from chat summary or randomly from `topics.txt`.
- Loads system prompts from `narration.prompt` (for avatar monologues) and `chat.prompt` (for chat responses).
- Both prompts use `{language}` placeholder, which is replaced with the full language name based on `--language` flag.
- Generates a 60–90 word monologue with OpenAI using the narration prompt and context history.
- Sends it to the AvatarTalk WebSocket RTMP gateway, which renders the avatar and streams to YouTube.
- Responds to viewer questions using the chat prompt and posts responses back to YouTube Live chat in chunks (max 200 characters per message).

## Troubleshooting
- **"YOUTUBE_API_KEY not provided"**: Set `YOUTUBE_API_KEY` and ensure YouTube Data API v3 is enabled.
- **"GOOGLE_CLIENT_SECRETS_PATH not set!"**: You need OAuth2 credentials for posting to chat. See "YouTube Setup" above.
- **"Topics file ... not found"**: Ensure `AVATARTALK_TOPICS_FILE` points to an existing file (default `topics.txt`).
- **OAuth2 browser window doesn't open**: Make sure you're running on a machine with a browser. The credentials are cached after first authorization.
- **No comments detected**: Confirm the stream is live and the `VIDEO_ID` is correct; check that the channel has an active live chat.
- **Cannot post to chat**: Verify OAuth2 authorization was successful and the account has permission to post to the channel's live chat.
- **WebSocket/auth errors**: Verify `AVATARTALK_API_KEY`, `AVATARTALK_AVATAR`, and RTMP settings.
- **No video on YouTube**: Double‑check `YOUTUBE_RTMP_URL` and `YOUTUBE_STREAM_KEY`, and that the stream is started in YouTube Studio.

