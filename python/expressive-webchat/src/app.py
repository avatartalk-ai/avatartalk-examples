import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import LANGUAGE_CHOICES, settings
from .orchestrator import ConversationOrchestrator

# Configure logging with timestamps for all client backend logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("client_app")

app = FastAPI(
    title="AvatarTalk Expressive WebChat", version="0.1.0", root_path=settings.ROOT_PATH
)

# Serve static files
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Setup Jinja2 templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "root_path": settings.ROOT_PATH,
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "expressive-webchat",
        }
    )


@app.get("/api/languages")
async def get_languages():
    """Return available languages for speech recognition."""
    languages = [{"code": code, "name": name} for code, name, _, _ in LANGUAGE_CHOICES]
    return JSONResponse(
        content={
            "languages": languages,
            "default": settings.DEFAULT_LANGUAGE,
        }
    )


@app.websocket("/ws/conversation")
async def conversation_endpoint(websocket: WebSocket):
    """Unified conversation WebSocket.

    This endpoint handles:
    - Text control messages (JSON) from browser (init, audio_config, buffer_status)
    - Binary audio data from browser microphone
    - Text control messages (JSON) to browser (status, session_ready)
    - Binary video data to browser (MP4 chunks from AvatarTalk)
    """
    await websocket.accept()

    orchestrator = ConversationOrchestrator()

    async def send_status(status: str):
        """Send status update to browser (JSON text frame)."""
        try:
            await websocket.send_json({"type": "status", "data": status})
        except Exception as e:
            logger.error(f"Error sending status to browser: {e}")

    async def send_session_ready(session_id: str):
        """Send session ready notification to browser (JSON text frame)."""
        try:
            await websocket.send_json(
                {
                    "type": "session_ready",
                    "data": {
                        "session_id": session_id,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Error sending session_ready to browser: {e}")

    async def send_video_data(video_bytes: bytes):
        """Forward video data to browser (binary frame)."""
        try:
            await websocket.send_bytes(video_bytes)
        except Exception as e:
            logger.error(f"Error sending video data to browser: {e}")

    orchestrator.on_status_change = send_status
    orchestrator.on_session_ready = send_session_ready
    orchestrator.on_video_data = send_video_data

    try:
        # Wait for init message with timeout
        try:
            data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=settings.INIT_MESSAGE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Init message timeout after {settings.INIT_MESSAGE_TIMEOUT}s"
            )
            await websocket.send_json(
                {"type": "error", "data": "Initialization timeout"}
            )
            return

        if data.get("type") != "init":
            logger.warning(f"Expected init message, got: {data.get('type')}")
            await websocket.send_json(
                {"type": "error", "data": "Expected init message"}
            )
            return

        payload = data.get("data", {})

        avatar = str(payload.get("avatar", settings.DEFAULT_AVATAR))
        expression = str(payload.get("expression", settings.DEFAULT_EXPRESSION))
        prompt = str(payload.get("prompt", settings.SYSTEM_PROMPT))
        language = str(payload.get("language", "en"))
        use_pregen = bool(payload.get("use_pregen", True))

        try:
            await orchestrator.start_session(
                avatar=avatar,
                expression=expression,
                prompt=prompt,
                language=language,
                use_pregen=use_pregen,
            )
        except ConnectionError as e:
            logger.error(f"Failed to start session: {e}")
            await websocket.send_json(
                {"type": "error", "data": f"Connection failed: {e}"}
            )
            return
        except Exception as e:
            logger.error(f"Unexpected error starting session: {e}")
            await websocket.send_json(
                {"type": "error", "data": "Failed to start session"}
            )
            return

        # Session ready notification will be sent via callback when AvatarTalk responds

        # Audio + control streaming loop
        while True:
            message = await websocket.receive()
            data_bytes = message.get("bytes")
            data_text = message.get("text")

            # Binary audio frames
            if data_bytes is not None:
                await orchestrator.process_audio(data_bytes)

            # Text control messages (e.g., audio_config)
            elif data_text:
                try:
                    control_msg = json.loads(data_text)
                except json.JSONDecodeError:
                    continue

                msg_type = control_msg.get("type")
                data_payload = control_msg.get("data", {})

                if msg_type == "audio_config":
                    sr = data_payload.get("sample_rate")
                    ch = data_payload.get("channel_count")
                    logger.info(
                        f"Received audio_config from browser: sample_rate={sr}, channels={ch}"
                    )
                    orchestrator.set_audio_config(sample_rate=sr, channel_count=ch)
                elif msg_type == "buffer_status":
                    buffered_ms = data_payload.get("buffered_ms")
                    playback_position = data_payload.get("playback_position")
                    if buffered_ms is not None:
                        await orchestrator.send_buffer_status(
                            float(buffered_ms), float(playback_position or 0.0)
                        )
                # Additional control messages can be handled here as needed

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Error in conversation: {e}", exc_info=True)
        try:
            await websocket.send_json(
                {"type": "error", "data": "Internal server error"}
            )
        except Exception:
            pass  # Client may have disconnected
    finally:
        try:
            await orchestrator.stop_session()
        except Exception as e:
            logger.error(f"Error stopping session: {e}")
