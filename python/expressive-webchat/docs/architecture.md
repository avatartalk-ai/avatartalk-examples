# Architecture

## Overview

The Expressive WebChat client enables natural voice conversations with AvatarTalk video avatars.

```
┌─────────────────┐
│     Browser     │  • Audio capture (AudioWorklet)
│   (Port 8080)   │  • Video playback (MediaSource)
│                 │  • Unified WebSocket
└────────┬────────┘
         │ WebSocket (mixed text/binary frames)
         ↓
┌─────────────────┐
│ Client Backend  │  • Conversation orchestration
│   FastAPI/uv    │  • Deepgram Flux (ASR + turn detection)
│                 │  • LiteLLM (GPT-4o-mini)
└────────┬────────┘
         │ WebSocket (control + video)
         ↓
┌─────────────────┐
│  AvatarTalk API │  • Authentication (Bearer token)
│                 │  • Video generation
│                 │  • MP4 streaming
└─────────────────┘
```

## Data Flow

### Conversation Cycle

1. **User Speaks** → Microphone captures audio → Browser sends to Client Backend
2. **Speech Recognition** → Deepgram Flux processes audio → Detects EndOfTurn after ~500ms silence
3. **Response Generation** → LiteLLM streams response → Sentences sent incrementally
4. **Avatar Response** → AvatarTalk generates video → MP4 streamed to browser
5. **Buffer Management** → Browser reports buffer level → Mic opens when buffer drains

## Key Components

### ConversationOrchestrator (`src/orchestrator.py`)

Manages the conversation state machine:
- Connects to Deepgram Flux for speech recognition
- Connects to AvatarTalk API for video generation
- Streams LLM responses sentence by sentence
- Handles expressive mode (LLM-controlled emotions)

### AvatarTalkClient (`src/avatartalk_client.py`)

WebSocket client for the AvatarTalk API:
- Authenticates via Bearer token
- Sends text for speech synthesis
- Receives MP4 video chunks
- Handles state change and ready_to_listen signals

### Browser Client (`static/js/client.js`)

- AudioWorklet for low-latency microphone capture
- MediaSource Extensions for video playback
- Buffer monitoring for adaptive mic control

## Expressive Mode

When enabled, the LLM dynamically selects avatar expressions:

1. LLM response includes JSON prefix: `{"expression": "happy"}`
2. Expression sent to AvatarTalk with first sentence
3. Avatar emotion changes based on conversation context

Available expressions: `happy`, `neutral`, `serious`
