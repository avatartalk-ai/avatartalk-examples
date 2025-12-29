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
            f"rtmp_url={rtmp_url}/{stream_key}"
        )
        if background_url:
            self.url += f"&background_url={background_url}"

        self._ws: websockets.ClientConnection | None = None

        # Reconnection configuration
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self._is_reconnecting = False

    async def initialize(self) -> None:
        self._ws = await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self.api_key}"})

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

                # Close existing connection if any
                if self._ws:
                    try:
                        await self._ws.close()
                    except (ConnectionClosed, ConnectionClosedOK):
                        # Already closed, this is fine
                        pass
                    except Exception as e:
                        # Log other errors but continue with reconnection
                        logger.warning("Error closing existing websocket: %s", e)
                    finally:
                        self._ws = None

                # Try to reconnect
                self._ws = await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self.api_key}"})
                logger.info("Successfully reconnected to AvatarTalk websocket")
                self._is_reconnecting = False
                return True

            except Exception as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)

                if attempt < self.max_reconnect_attempts:
                    logger.info("Waiting %.1f seconds before retry...", backoff)
                    await asyncio.sleep(backoff)
                    # Exponential backoff with max cap
                    backoff = min(backoff * 2, self.max_backoff)

        logger.error("Failed to reconnect after %d attempts", self.max_reconnect_attempts)
        self._is_reconnecting = False
        return False

    async def send(self, text_content: str) -> None:
        try:
            if not self._ws:
                raise RuntimeError("WebSocket connection is not initialized")
            await self._ws.send(text_content.encode("utf-8"))
        except (ConnectionClosed, ConnectionClosedOK) as e:
            logger.warning("WebSocket connection closed during send: %s", e)
            # Attempt to reconnect
            if await self._reconnect():
                # Retry the send after successful reconnection
                await self._ws.send(text_content.encode("utf-8"))
            else:
                raise RuntimeError("Failed to reconnect to websocket") from e
        except Exception as e:
            logger.exception("Error sending message: %s", e)
            raise

    async def receive(self) -> dict[str, Any]:
        while True:
            try:
                if not self._ws:
                    raise RuntimeError("WebSocket connection is not initialized")
                raw = await asyncio.wait_for(self._ws.recv(), timeout=5)
                return json.loads(raw)
            except TimeoutError:
                logger.debug("No message received in 5 seconds, retrying...")
                await asyncio.sleep(5)
                continue
            except (ConnectionClosed, ConnectionClosedOK) as e:
                logger.warning("WebSocket connection closed during receive: %s", e)
                # Attempt to reconnect
                if await self._reconnect():
                    logger.info("Reconnected successfully, continuing to receive...")
                    continue
                raise RuntimeError("Failed to reconnect to websocket") from e
            except Exception as e:
                logger.exception("Error receiving message: %s", e)
                raise

    async def close(self) -> None:
        if not self._ws:
            return
        try:
            await self.send("!!!Close!!!")
        finally:
            await self._ws.close()
