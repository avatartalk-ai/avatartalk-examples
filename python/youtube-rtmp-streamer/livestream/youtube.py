import logging
import sys
from datetime import UTC, datetime
from typing import Any

import requests
from openai import OpenAI

from livestream.config import AVATARTALK_MODEL

logger = logging.getLogger(__name__)


class YouTubeCommentManager:
    """Manages YouTube Live chat comment retrieval and processing."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.live_chat_id: str | None = None
        self.next_page_token: str | None = None
        self.last_check_time = datetime.now(UTC)
        self.openai_client = OpenAI()
        self.model = AVATARTALK_MODEL
        self.system_prompt = (
            "You are a helpful assistant that summarizes YouTube Live chat comments. "
            "Summarize the comments in a single sentence."
        )

    def find_live_stream(self, channel_name: str = "avatartalk") -> str | None:
        """Find the current live stream ID for the given channel."""
        try:
            channel_id = self._get_channel_id(channel_name)
            if not channel_id:
                logger.warning("Channel %s not found", channel_name)
                return None

            # Search for live streams
            search_url = f"{self.base_url}/search"
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "eventType": "live",
                "key": self.api_key,
            }

            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("items"):
                video_id = data["items"][0]["id"]["videoId"]
                print(f"Found live stream: {video_id}", file=sys.stderr)
                return video_id
            logger.info("No live stream found")
            return None

        except Exception as e:
            logger.exception("Error finding live stream: %s", e)
            return None

    def _get_channel_id(self, channel_name: str) -> str | None:
        """Get channel ID from channel name."""
        try:
            search_url = f"{self.base_url}/search"
            params = {"part": "snippet", "q": channel_name, "type": "channel", "key": self.api_key}

            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("items"):
                return data["items"][0]["id"]["channelId"]
            return None

        except Exception as e:
            logger.exception("Error getting channel ID: %s", e)
            return None

    def get_live_chat_id(self, video_id: str) -> str | None:
        """Get live chat ID from video ID."""
        try:
            videos_url = f"{self.base_url}/videos"
            params = {"part": "snippet,liveStreamingDetails", "id": video_id, "key": self.api_key}

            response = requests.get(videos_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("items") and data["items"][0].get("liveStreamingDetails"):
                live_chat_id = data["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    self.live_chat_id = live_chat_id
                    print(f"Live chat ID: {live_chat_id}", file=sys.stderr)
                    return live_chat_id

            raise ValueError("Live chat ID not found")

        except Exception as e:
            logger.exception("Error getting live chat ID: %s", e)
            return None

    def get_recent_comments(self) -> list[dict[str, Any]]:
        """Get recent comments from YouTube Live chat."""
        if not self.live_chat_id:
            return []

        try:
            messages_url = f"{self.base_url}/liveChat/messages"
            params = {"liveChatId": self.live_chat_id, "part": "snippet,authorDetails", "key": self.api_key}

            if self.next_page_token:
                params["pageToken"] = self.next_page_token

            response = requests.get(messages_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Update next page token
            self.next_page_token = data.get("nextPageToken")

            # Filter comments since last check
            comments: list[dict[str, Any]] = []
            current_time = datetime.now(UTC)

            for item in data.get("items", []):
                snippet = item["snippet"]
                author = item["authorDetails"]

                # Parse timestamp
                published_at = datetime.fromisoformat(snippet["publishedAt"]).replace(tzinfo=UTC)

                if published_at > self.last_check_time:
                    details = snippet.get("textMessageDetails") or {}
                    text = details.get("messageText", "")
                    comments.append(
                        {
                            "text": text,
                            "author": author.get("displayName", ""),
                            "timestamp": published_at,
                            "is_moderator": author.get("isChatModerator", False),
                            "is_owner": author.get("isChatOwner", False),
                        }
                    )

            self.last_check_time = current_time
            return comments
        except Exception as e:
            logger.exception("Error getting comments: %s", e)
            return []

    def summarize_comments(self, comments: list[dict[str, Any]]) -> str:
        """Summarize comments into a single sentence topic string."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n".join([f"{c['author']}: {c['text']}" for c in comments])},
        ]

        try:
            response = self.openai_client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=200, temperature=0.8
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.exception("OpenAI API error: %s", e)
            raise
