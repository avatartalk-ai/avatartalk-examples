import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

DEFAULT_API_URL = "wss://api.avatartalk.ai"
logger = logging.getLogger(__name__)


class AvatarTalkConnector:
    """Thin wrapper around the AvatarTalk WebSocket/RTMP gateway."""

    def __init__(
        self,
        url: str,
        api_key: str,
        avatar: str,
        language: str,
        rtmp_url: str,
        stream_key: str,
        background_url: str | None = None,
        silence_duration: float = 4.0,
        tts_provider: str | None = None,
        max_reconnect_attempts: int = 5,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self.avatar = avatar
        self.emotion = "neutral"
        self.language = language
        self.room_name = "avatartalk-live"
        self.api_url = url or DEFAULT_API_URL
        self.api_key = api_key
        self.silence_duration = silence_duration
        self.tts_provider = tts_provider
        if not rtmp_url or not stream_key:
            raise ValueError("YOUTUBE_RTMP_URL and YOUTUBE_STREAM_KEY are required for RTMP output")
        self.url = (
            f"{self.api_url}/ws/infer?"
            "output_type=rtmp&"
            "input_type=text&"
            f"stream_id={self.room_name}&"
            f"avatar={self.avatar}&"
            f"emotion={self.emotion}&"
            f"language={self.language}&"
            f"increase_resolution=true&"
            f"silence_duration={self.silence_duration}&"
            f"rtmp_url={rtmp_url}/{stream_key}"
        )
        if background_url:
            self.url += f"&background_url={background_url}"
        if self.tts_provider:
            self.url += f"&tts_provider={self.tts_provider}"

        self._ws: websockets.ClientConnection | None = None
        self._lock = asyncio.Lock()
        self.reconnected_event = False

        # Reconnection configuration
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self._is_reconnecting = False

    async def initialize(self) -> None:
        self._ws = await websockets.connect(
            self.url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            ping_interval=20,
            ping_timeout=20,
        )

    async def _close_raw_ws(self) -> None:
        """Close the underlying websocket without sending sentinel or reconnecting."""
        if not self._ws:
            return
        ws = self._ws
        self._ws = None
        try:
            await ws.close()
        except (ConnectionClosed, ConnectionClosedOK):
            pass
        except Exception as e:
            logger.debug("Ignored error closing raw websocket: %s", e)

    async def _reconnect(self) -> bool:
        """
        Attempt to reconnect to the websocket with exponential backoff.

        Returns:
            True if reconnection succeeded, False otherwise.

        """
        if self._is_reconnecting:
            logger.debug("Reconnection already in progress, skipping")
            return False

        self._is_reconnecting = True
        backoff = self.initial_backoff

        for attempt in range(1, self.max_reconnect_attempts + 1):
            try:
                logger.info("Attempting to reconnect (attempt %d/%d)...", attempt, self.max_reconnect_attempts)
                await self._close_raw_ws()

                self._ws = await websockets.connect(
                    self.url,
                    additional_headers={"Authorization": f"Bearer {self.api_key}"},
                    ping_interval=20,
                    ping_timeout=20,
                )
                logger.info("Successfully reconnected to AvatarTalk websocket")
                self.reconnected_event = True
                self._is_reconnecting = False
                return True

            except Exception as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)

                if attempt < self.max_reconnect_attempts:
                    logger.info("Waiting %.1f seconds before retry...", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.max_backoff)

        logger.error("Failed to reconnect after %d attempts", self.max_reconnect_attempts)
        self._is_reconnecting = False
        return False

    async def restart(self) -> bool:
        """Thread/task-safe restart of the websocket connection (used by healthcheck)."""
        async with self._lock:
            return await self._reconnect()

    async def send_and_receive(self, text_content: str, timeout: float = 45.0) -> dict[str, Any]:
        """
        Atomically send text and wait for the server's audio_duration response.

        If the connection drops during send or receive, reconnects and resends the payload
        once so that `receive` never hangs waiting on a fresh socket that received no request.
        """
        payload = text_content.encode("utf-8")
        async with self._lock:
            for attempt in range(2):
                try:
                    if not self._ws:
                        if not await self._reconnect():
                            raise RuntimeError("WebSocket connection is not initialized and reconnect failed")
                    await self._ws.send(payload)
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
                    return json.loads(raw)
                except TimeoutError:
                    logger.warning(
                        "Timed out waiting %.1fs for AvatarTalk response (attempt %d/2); reconnecting...",
                        timeout,
                        attempt + 1,
                    )
                    if not await self._reconnect():
                        raise RuntimeError("Failed to reconnect after receive timeout") from None
                except (ConnectionClosed, ConnectionClosedOK) as e:
                    logger.warning("WebSocket closed during send_and_receive (attempt %d/2): %s", attempt + 1, e)
                    if not await self._reconnect():
                        raise RuntimeError("Failed to reconnect to websocket") from e
                except Exception as e:
                    logger.exception("Unexpected error in send_and_receive: %s", e)
                    raise
            return {"audio_duration": 0.0}

    async def send(self, text_content: str) -> None:
        try:
            if not self._ws:
                raise RuntimeError("WebSocket connection is not initialized")
            await self._ws.send(text_content.encode("utf-8"))
        except (ConnectionClosed, ConnectionClosedOK) as e:
            logger.warning("WebSocket connection closed during send: %s", e)
            if await self._reconnect():
                await self._ws.send(text_content.encode("utf-8"))
            else:
                raise RuntimeError("Failed to reconnect to websocket") from e
        except Exception as e:
            logger.exception("Error sending message: %s", e)
            raise

    async def receive(self, timeout: float = 45.0) -> dict[str, Any]:
        if not self._ws:
            raise RuntimeError("WebSocket connection is not initialized")
        raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        return json.loads(raw)

    async def close(self) -> None:
        async with self._lock:
            if not self._ws:
                return
            try:
                await asyncio.wait_for(self._ws.send(b"!!!Close!!!"), timeout=2.0)
            except Exception as e:
                logger.debug("Could not send close sentinel (socket likely already closed): %s", e)
            finally:
                await self._close_raw_ws()
