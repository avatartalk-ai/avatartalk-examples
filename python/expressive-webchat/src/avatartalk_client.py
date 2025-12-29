import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

# Default timeouts
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_CLOSE_TIMEOUT = 5.0


class AvatarTalkClient:
    """Client for AvatarTalk WebSocket streaming.

    Uses a single WebSocket connection for both control messages (JSON text frames)
    and video streaming (binary frames).

    Authentication: Bearer token via `Authorization: Bearer <AVATARTALK_API_KEY>` header.
    """

    def __init__(self, url: str, api_key: str = "", connect_timeout: float = DEFAULT_CONNECT_TIMEOUT):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.connect_timeout = connect_timeout
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.session_id: Optional[str] = None
        self._connected = False
        self._closing = False

        # Connection params
        self._avatar: Optional[str] = None
        self._expression: Optional[str] = None
        self._language: str = "en"

        # Control message callbacks
        self.on_state_change: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.on_ready_to_listen: Optional[Callable[[], Awaitable[None]]] = None
        self.on_session_ready: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_disconnect: Optional[Callable[[], Awaitable[None]]] = None

        # Video data callback - receives binary MP4 chunks
        self.on_video_data: Optional[Callable[[bytes], Awaitable[None]]] = None

        self._listen_task: Optional[asyncio.Task] = None

    async def connect(
        self,
        avatar: Optional[str] = None,
        expression: Optional[str] = None,
        language: str = "en",
    ):
        """Connect to the AvatarTalk WebSocket endpoint.

        Avatar, expression, and language are included as query params.
        """
        self._avatar = avatar
        self._expression = expression
        self._language = language

        query_params = {}
        if avatar:
            query_params["avatar"] = avatar
        if expression:
            query_params["expression"] = expression
        if language:
            query_params["language"] = language

        uri = f"{self.url}/ws/continuous"
        if query_params:
            uri += f"?{urlencode(query_params)}"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            logger.info(f"Connecting to AvatarTalk API: {uri} (auth: Bearer token)")
        else:
            logger.warning(f"Connecting to AvatarTalk API without authentication: {uri}")

        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    uri,
                    additional_headers=headers,
                    ping_interval=20,  # Send ping every 20s to keep connection alive
                    ping_timeout=10,  # Wait 10s for pong response
                    close_timeout=DEFAULT_CLOSE_TIMEOUT,
                ),
                timeout=self.connect_timeout,
            )
            self._connected = True
            self._closing = False
            self._listen_task = asyncio.create_task(self._listen_loop())
        except asyncio.TimeoutError:
            logger.error(f"Connection to AvatarTalk timed out after {self.connect_timeout}s")
            raise ConnectionError(f"Connection timeout after {self.connect_timeout}s")
        except WebSocketException as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise ConnectionError(f"WebSocket connection failed: {e}")

    def _check_connected(self) -> None:
        """Raise if not connected."""
        if not self._connected or not self.ws:
            raise ConnectionError("Not connected to AvatarTalk API")

    async def start_session(
        self,
        avatar: str,
        expression: str,
        language: str = "en",
        expressive_mode: bool = False,
        target_buffer_ms: int = 500,
        min_buffer_ms: int = 250,
        max_buffer_ms: int = 1500,
    ):
        """Start a new streaming session.

        Args:
            avatar: Avatar name (required)
            expression: Initial expression (required)
            language: Language code, defaults to "en"
            expressive_mode: If True, preload all expressions for dynamic switching
            target_buffer_ms: Target video buffer in milliseconds
            min_buffer_ms: Minimum video buffer
            max_buffer_ms: Maximum video buffer
        """
        self._check_connected()

        data = {
            "avatar_name": avatar,
            "expression": expression,
            "language": language,
            "expressive_mode": expressive_mode,
            "target_buffer_ms": target_buffer_ms,
            "min_buffer_ms": min_buffer_ms,
            "max_buffer_ms": max_buffer_ms,
        }

        msg = {"type": "session_start", "data": data}
        logger.info(f"Sending session_start: avatar={avatar}, expression={expression}")
        await self.ws.send(json.dumps(msg))

    async def send_text(
        self,
        text: str,
        expression: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        """Send text to be spoken.

        The optional ``mode`` parameter is forwarded to the server as part of
        the text_input payload (e.g. ``"dynamic_only"`` to trigger a
        direct silence→dynamic path without a pregen stage).
        """
        self._check_connected()

        data = {"text": text}
        if expression is not None:
            data["expression"] = expression
        if mode is not None:
            data["mode"] = mode

        msg = {"type": "text_input", "data": data}
        await self.ws.send(json.dumps(msg))

    async def send_turn_start(self, expression: Optional[str] = None):
        """Trigger an End-of-Turn pregenerated segment.

        This sends a ``turn_start`` control message which causes the server
        to play a pregenerated connective clip from the current silence
        state, then return back to silence without starting dynamic speech.
        """
        self._check_connected()

        data: dict = {}
        if expression is not None:
            data["expression"] = expression

        msg = {"type": "turn_start", "data": data}
        await self.ws.send(json.dumps(msg))

    async def append_text(self, text: str):
        """Append additional text to an ongoing dynamic speech generation.

        This is used for streaming LLM responses where sentences arrive
        incrementally. The server queues this text for synthesis and video
        generation while the current speech is still playing.
        """
        self._check_connected()

        data = {"text": text}
        msg = {"type": "text_append", "data": data}
        await self.ws.send(json.dumps(msg))

    async def finish_text_stream(self):
        """Signal that no more text will be appended.

        This tells the server that the LLM streaming is complete and it can
        finalize the audio/video generation for the current response.
        """
        self._check_connected()

        msg = {"type": "text_stream_done", "data": {}}
        await self.ws.send(json.dumps(msg))

    async def send_buffer_status(self, buffered_ms: float, playback_position: float):
        """Send client-side video buffer status for adaptive streaming."""
        self._check_connected()

        msg = {
            "type": "buffer_status",
            "data": {
                "buffered_ms": buffered_ms,
                "playback_position": playback_position,
            },
        }
        await self.ws.send(json.dumps(msg))

    async def _listen_loop(self):
        """Listen for messages on the unified WebSocket.

        Handles both:
        - Text frames: JSON control messages
        - Binary frames: MP4 video data
        """
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    # Binary frame - video data
                    if self.on_video_data:
                        await self.on_video_data(message)
                else:
                    # Text frame - JSON control message
                    data = json.loads(message)
                    msg_type = data.get("type")
                    msg_data = data.get("data", {})

                    if msg_type == "session_ready":
                        self.session_id = msg_data.get("session_id")
                        logger.info(f"AvatarTalk Session Ready: {self.session_id}")
                        if self.on_session_ready and self.session_id is not None:
                            await self.on_session_ready(self.session_id)

                    elif msg_type == "state_change":
                        from_state = msg_data.get("from")
                        to_state = msg_data.get("to")
                        if self.on_state_change:
                            await self.on_state_change(from_state, to_state)

                    elif msg_type == "ready_to_listen":
                        if self.on_ready_to_listen:
                            await self.on_ready_to_listen()

                    elif msg_type == "error":
                        error_msg = msg_data.get("message", "Unknown error")
                        logger.error(f"AvatarTalk error: {error_msg}")
                        if self.on_error:
                            await self.on_error(error_msg)

                    elif msg_type in (
                        "text_queued",
                        "text_appended",
                        "text_stream_completed",
                        "turn_queued",
                        "pong",
                    ):
                        # Acknowledgments - log but no action needed
                        logger.debug(f"Received {msg_type}: {msg_data}")

                    else:
                        logger.debug(f"Unhandled message type: {msg_type}")

        except ConnectionClosed as e:
            if not self._closing:
                logger.warning(f"AvatarTalk connection closed unexpectedly: {e}")
            else:
                logger.info(f"AvatarTalk connection closed: {e}")
        except asyncio.CancelledError:
            logger.debug("AvatarTalk listen loop cancelled")
        except Exception as e:
            logger.error(f"AvatarTalk connection error: {e}", exc_info=True)
        finally:
            self._connected = False
            if self.on_disconnect and not self._closing:
                try:
                    await self.on_disconnect()
                except Exception as e:
                    logger.error(f"Error in disconnect callback: {e}")

    async def disconnect(self):
        """Gracefully disconnect from the AvatarTalk API."""
        if self._closing:
            return
        self._closing = True
        self._connected = False

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=DEFAULT_CLOSE_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Timeout closing WebSocket, forcing close")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self.ws = None

        self.session_id = None
        logger.info("Disconnected from AvatarTalk API")
