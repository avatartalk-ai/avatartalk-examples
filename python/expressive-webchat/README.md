# AvatarTalk · Expressive WebChat (Python, uv app)

## Overview

- Natural voice conversations with video avatars featuring automatic turn-taking and emotional expressions.
- Deepgram Flux automatically detects when you finish speaking (no buttons needed).
- LLM selects appropriate avatar expressions (happy, neutral, serious) based on conversation context.
- Ultra-low latency streaming with < 1 second end-to-end response time.
- Stack: FastAPI, `deepgram-sdk` (Flux ASR), `litellm` (GPT-4o-mini), `websockets`, `python-dotenv`.

### Environment Variables

- `OPENAI_API_KEY` (required) – OpenAI API key for LLM responses
- `DEEPGRAM_API_KEY` (required) – Deepgram API key for speech recognition
- `AVATARTALK_API_KEY` (required) – AvatarTalk API key
- `AVATARTALK_API_BASE` (optional, default: `wss://api.avatartalk.ai`)
- `DEFAULT_AVATAR` (optional, default: `mexican_woman`, other not available for now, can be requested)
- `DEFAULT_EXPRESSION` (optional, default: `neutral`)
- `DEFAULT_LANGUAGE` (optional, default: `en`) – Default language for speech recognition
- `LLM_MODEL` (optional, default: `gpt-4o-mini`)
- `SYSTEM_PROMPT` (optional) – Custom system prompt for the avatar

This app loads `.env` automatically using `python-dotenv`.

## Quick Start

1) Ensure Python 3.10+ and install `uv`
2) In this folder (`python/expressive-webchat`), create a `.env` with at least:
   - `OPENAI_API_KEY=sk-...`
   - `DEEPGRAM_API_KEY=...`
   - `AVATARTALK_API_KEY=at_...`
3) Run the app:
   - `./run.sh`
   - Or: `uv run uvicorn src.app:app --reload --port 8080`
4) Open http://localhost:8080 and start a conversation.
   - Click "Start Session" and allow microphone access.
   - Speak naturally; the avatar responds with appropriate emotions.

#### Notes

- The server bridges the AvatarTalk WebSocket connection with `Authorization: Bearer <AVATARTALK_API_KEY>`.
- Audio capture uses AudioWorklet for low-latency streaming to Deepgram Flux.
- Video playback uses MediaSource Extensions for smooth MP4 streaming.
- Expressive mode: Select "Expressive (LLM-controlled)" to let the LLM dynamically control avatar emotions.

## Layout

- `src/app.py` – FastAPI app and WebSocket endpoint
  - `WS /ws/conversation` – unified WebSocket for audio/video/control
- `src/config.py` – env loading and settings
- `src/orchestrator.py` – conversation orchestration, Deepgram Flux, LLM streaming
- `src/avatartalk_client.py` – AvatarTalk WebSocket client
- `static/index.html` – web UI
- `static/js/client.js` – browser client (AudioWorklet + MediaSource)

## Features

- **Natural Turn-Taking**: Deepgram Flux detects when you finish speaking (~500ms silence)
- **Emotional Responses**: LLM selects expressions (happy, neutral, serious)
- **Streaming LLM**: Sentences are processed as they arrive, reducing wait time
- **Buffer-Aware Mic Control**: Microphone opens only when avatar visually finishes speaking
- **Multi-Language Support**: 17 languages supported with automatic ASR model selection
  - English: Deepgram Flux (optimized turn detection)
  - Spanish, French, German, Italian, Portuguese, Russian, Dutch, Japanese, Hindi: Deepgram Nova-3 (multilingual)
  - Polish, Turkish, Czech, Arabic, Chinese, Hungarian, Korean: Deepgram Nova-2 (language-specific models)

See `docs/` for additional technical documentation.
