import asyncio
import json
import logging
from typing import Any

import websockets

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

    async def initialize(self) -> None:
        self._ws = await websockets.connect(self.url, additional_headers={"Authorization": f"Bearer {self.api_key}"})

    async def send(self, text_content: str) -> None:
        try:
            if not self._ws:
                raise RuntimeError("WebSocket connection is not initialized")
            await self._ws.send(text_content.encode("utf-8"))
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
