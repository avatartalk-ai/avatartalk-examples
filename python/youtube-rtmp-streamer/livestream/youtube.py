import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import nltk
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from nltk.tokenize import sent_tokenize
from openai import OpenAI

from livestream.config import AVATARTALK_MODEL, GOOGLE_CLIENT_SECRETS_PATH

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl"]

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

nltk.download("punkt")
nltk.download("punkt_tab")


class YouTubeCommentManager:
    """Manages YouTube Live chat comment retrieval and processing."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.live_chat_id: str | None = None
        self.next_page_token: str | None = None
        self.polling_interval_ms: int = 2000  # Default 2 seconds, updated from API
        self.openai_client = OpenAI()
        self.model = AVATARTALK_MODEL
        self.system_prompt = (
            "You are a helpful assistant that summarizes YouTube Live chat comments. "
            "Summarize the comments in a single sentence."
        )
        self.secrets_path = GOOGLE_CLIENT_SECRETS_PATH
        creds = None

        if not self.secrets_path:
            raise ValueError("GOOGLE_CLIENT_SECRETS_PATH not set!")

        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(self.secrets_path, SCOPES)
                creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open("token.json", "w") as token:
                    token.write(creds.to_json())

        self.youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=creds)

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
            request = self.youtube.channels().list(part="snippet,contentDetails,statistics", mine=True)

            response = request.execute()
            return response["items"][0]["id"]

        except Exception as e:
            logger.exception("Error getting channel ID: %s", e)
            return None

    def get_live_chat_id(self, video_id: str) -> str | None:
        """Get live chat ID from video ID."""
        try:
            request = self.youtube.videos().list(part="snippet,liveStreamingDetails", id=video_id)
            response = request.execute()

            if response.get("items") and response["items"][0].get("liveStreamingDetails"):
                live_chat_id = response["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    self.live_chat_id = live_chat_id
                    print(f"Live chat ID: {live_chat_id}", file=sys.stderr)
                    return live_chat_id

            raise ValueError("Live chat ID not found")

        except Exception as e:
            logger.exception("Error getting live chat ID: %s", e)
            return None

    def get_recent_comments(self) -> list[dict[str, Any]]:
        """
        Get recent comments from YouTube Live chat using authenticated API client.

        Uses the YouTube Data API v3 liveChatMessages.list endpoint with proper
        OAuth2 authentication. The pageToken mechanism automatically handles
        which messages are new - we don't need to filter by timestamp.

        YouTube's paging for live chat works differently than regular paging:
        - The pageToken marks our position in the message stream
        - Only NEW messages since the last pageToken are returned
        - This is why we don't need timestamp filtering

        Returns:
            List of comment dictionaries with text, author, timestamp, and metadata

        """
        if not self.live_chat_id:
            return []

        try:
            # Build request using authenticated youtube client
            request = self.youtube.liveChatMessages().list(
                liveChatId=self.live_chat_id,
                part="snippet,authorDetails",
                pageToken=self.next_page_token if self.next_page_token else None,
            )

            response = request.execute()

            # Update next page token for proper paging
            self.next_page_token = response.get("nextPageToken")

            # Update polling interval (YouTube tells us how often to poll)
            self.polling_interval_ms = response.get("pollingIntervalMillis", 2000)
            logger.debug("YouTube polling interval: %dms", self.polling_interval_ms)

            # Process all items returned (pageToken already handles what's "new")
            comments: list[dict[str, Any]] = []

            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                author = item.get("authorDetails", {})

                # Skip messages from the chat owner (our bot)
                if author.get("isChatOwner", False):
                    continue

                # Handle different message types
                message_type = snippet.get("type", "textMessageEvent")

                if message_type == "textMessageEvent":
                    details = snippet.get("textMessageDetails", {})
                    text = details.get("messageText", "")
                else:
                    # Skip non-text messages (super chats, stickers, etc.)
                    logger.debug("Skipping non-text message type: %s", message_type)
                    continue

                # Parse timestamp
                published_at_str = snippet.get("publishedAt")
                if not published_at_str:
                    continue

                published_at = datetime.fromisoformat(published_at_str)

                if text:  # Only include messages with actual text
                    comments.append(
                        {
                            "text": text,
                            "author": author.get("displayName", "Unknown"),
                            "timestamp": published_at,
                            "is_moderator": author.get("isChatModerator", False),
                            "is_owner": author.get("isChatOwner", False),
                            "channel_id": author.get("channelId", ""),
                        }
                    )

            logger.debug("Retrieved %d new comments", len(comments))
            return comments

        except HttpError as e:
            logger.exception("YouTube API HTTP error getting comments: %s", e)
            return []
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

    def send_chat_message(self, message):
        """
        Send a message to a live stream chat

        Args:
            youtube: Authenticated YouTube API service
            live_chat_id: The live chat ID (get from broadcast)
            message: The message text to send

        Returns:
            The response from the API or None if failed

        """
        try:
            for msg_chunk in self.split_into_chunks(message):
                request = self.youtube.liveChatMessages().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "liveChatId": self.live_chat_id,
                            "type": "textMessageEvent",
                            "textMessageDetails": {"messageText": msg_chunk},
                        }
                    },
                )

                response = request.execute()
                time.sleep(1)

            logger.info("Message sent successfully!")

            return response

        except HttpError as e:
            print(f"An HTTP error {e.resp.status} occurred:")
            print(e.content)
            return None

    def split_into_chunks(self, text: str, max_characters: int = 200):
        current_chunk = ""
        for sentence in sent_tokenize(text):
            if len(current_chunk + sentence) < max_characters:
                current_chunk = f"{current_chunk} {sentence}"
            else:
                chunk_to_return = current_chunk
                current_chunk = sentence
                yield chunk_to_return

        yield current_chunk
