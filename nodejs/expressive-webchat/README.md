# AvatarTalk · Expressive WebChat (Node.js)

## Overview

- IMPORTANT - This client uses Deepgram Nova 2 instead of Flux. For Flux support, see the Python example.
- Natural voice conversations with video avatars featuring automatic turn-taking and emotional expressions.
- Deepgram automatically detects when you finish speaking (no buttons needed).
- LLM selects appropriate avatar expressions (happy, neutral, serious) based on conversation context.
- Ultra-low latency streaming with < 1 second end-to-end response time.
- Stack: Express, `express-ws`, `@deepgram/sdk` (ASR), `openai` (GPT-4o-mini), `ws`, `dotenv`.

### Environment Variables

- `OPENAI_API_KEY` (required) – OpenAI API key for LLM responses
- `DEEPGRAM_API_KEY` (required) – Deepgram API key for speech recognition
- `AVATARTALK_API_KEY` (required) – AvatarTalk API key
- `AVATARTALK_API_BASE` (optional, default: `wss://api.avatartalk.ai`)
- `DEFAULT_AVATAR` (optional, default: `mexican_woman`, other not available for now, can be requested)
- `DEFAULT_EXPRESSION` (optional, default: `neutral`)
- `LLM_MODEL` (optional, default: `gpt-4o-mini`)
- `SYSTEM_PROMPT` (optional) – Custom system prompt for the avatar

This app loads `.env` automatically using `dotenv`.

## Quick Start

1) Ensure Node.js 18+
2) In this folder (`nodejs/expressive-webchat`), create a `.env` with at least:
   - `OPENAI_API_KEY=sk-...`
   - `DEEPGRAM_API_KEY=...`
   - `AVATARTALK_API_KEY=at_...`
3) Install deps and run:
   - `npm install`
   - `npm start`
4) Open http://localhost:8080 and start a conversation.
   - Click "Start Session" and allow microphone access.
   - Speak naturally; the avatar responds with appropriate emotions.

#### Notes

- The server bridges the AvatarTalk WebSocket connection with `Authorization: Bearer <AVATARTALK_API_KEY>`.
- Audio capture uses AudioWorklet for low-latency streaming to Deepgram.
- Video playback uses MediaSource Extensions for smooth MP4 streaming.
- Expressive mode: Select "Expressive (LLM-controlled)" to let the LLM dynamically control avatar emotions.

## Layout

- `src/app.js` – Express app and WebSocket endpoint
  - `WS /ws/conversation` – unified WebSocket for audio/video/control
- `src/config.js` – env loading and settings
- `src/orchestrator.js` – conversation orchestration, Deepgram, LLM streaming
- `src/avatartalk_client.js` – AvatarTalk WebSocket client
- `static/index.html` – web UI
- `static/js/client.js` – browser client (AudioWorklet + MediaSource)

## Features

- **Natural Turn-Taking**: Deepgram detects when you finish speaking (~500ms silence)
- **Emotional Responses**: LLM selects expressions (happy, neutral, serious)
- **Streaming LLM**: Sentences are processed as they arrive, reducing wait time
- **Buffer-Aware Mic Control**: Microphone opens only when avatar visually finishes speaking
