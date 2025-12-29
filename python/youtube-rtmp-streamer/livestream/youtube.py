import logging
import os
import sys
import time
from datetime import datetime, UTC
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

# Download NLTK data only if not already present
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    logger.info("Downloading NLTK punkt tokenizer...")
    nltk.download("punkt", quiet=True)

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    logger.info("Downloading NLTK punkt_tab tokenizer...")
    nltk.download("punkt_tab", quiet=True)


class YouTubeCommentManager:
    """Manages YouTube Live chat comment retrieval and processing."""

    def __init__(self, api_key: str, openai_client: OpenAI | None = None):
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.live_chat_id: str | None = None
        self.next_page_token: str | None = None
        self.polling_interval_ms: int = 2000  # Default 2 seconds, updated from API
        # Accept OpenAI client from caller to avoid creating multiple instances
        self.openai_client = openai_client if openai_client else OpenAI()
        self._owns_openai_client = openai_client is None  # Track if we created the client
        self.model = AVATARTALK_MODEL
        self.system_prompt = (
            "You are a helpful assistant that summarizes YouTube Live chat comments. "
            "Summarize the comments in a single sentence."
        )
        self.secrets_path = GOOGLE_CLIENT_SECRETS_PATH
        self.chat_start_ts = None
        creds = None

        # Initialize requests session for connection pooling
        self.requests_session = requests.Session()

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

        # Build YouTube API client with cache_discovery=False to prevent memory leaks
        # See: https://github.com/googleapis/google-api-python-client/issues/299
        self.youtube = googleapiclient.discovery.build(
            API_SERVICE_NAME,
            API_VERSION,
            credentials=creds,
            cache_discovery=False  # Prevents httplib2 cache buildup
        )

    async def close(self) -> None:
        """Clean up resources (OpenAI client, requests session, YouTube API client)."""
        logger.info("Closing YouTubeCommentManager resources...")

        # Close OpenAI client only if we created it
        try:
            if self._owns_openai_client and self.openai_client:
                self.openai_client.close()
                logger.debug("OpenAI client closed")
        except Exception as e:
            logger.error("Error closing OpenAI client: %s", e)

        # Close requests session
        try:
            if hasattr(self, 'requests_session') and self.requests_session:
                self.requests_session.close()
                logger.debug("Requests session closed")
        except Exception as e:
            logger.error("Error closing requests session: %s", e)

        # Close YouTube API client
        try:
            if hasattr(self, 'youtube') and self.youtube:
                self.youtube.close()
                logger.debug("YouTube API client closed")
        except Exception as e:
            logger.error("Error closing YouTube API client: %s", e)

        logger.info("YouTubeCommentManager resources closed")

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

            response = self.requests_session.get(search_url, params=params, timeout=10)
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
                    if not self.chat_start_ts:
                        self.chat_start_ts = datetime.now(UTC)

                    return live_chat_id

            raise ValueError("Live chat ID not found")

        except Exception as e:
            logger.exception("Error getting live chat ID: %s", e)
            return None

    def check_for_bot_messages(self, search_text: str | None = None, max_messages: int = 50) -> bool:
        """
        Check if the bot has already posted messages to the chat.

        This is useful for detecting if the stream was restarted,
        preventing duplicate greetings.

        Args:
            search_text: Optional text to search for in bot messages (case-insensitive).
                        If None, just checks if ANY bot messages exist.
            max_messages: Maximum number of recent messages to check

        Returns:
            True if bot message was found (matching search_text if provided), False otherwise
        """
        if not self.live_chat_id:
            logger.warning("Cannot check bot messages: live_chat_id not set")
            return False

        try:
            if search_text:
                logger.debug("Checking for bot messages containing: %s", search_text)
            else:
                logger.debug("Checking if bot has posted any messages")

            # Fetch recent chat messages without filtering by owner
            request = self.youtube.liveChatMessages().list(
                liveChatId=self.live_chat_id,
                part="snippet,authorDetails",
                maxResults=max_messages,
            )

            response = request.execute()
            search_lower = search_text.lower() if search_text else None

            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                author = item.get("authorDetails", {})

                # Only check messages from the bot (chat owner)
                if not author.get("isChatOwner", False):
                    continue

                # Check text messages
                if snippet.get("type") == "textMessageEvent":
                    details = snippet.get("textMessageDetails", {})
                    text = details.get("messageText", "")

                    # If no search text, any bot message counts
                    if not search_lower:
                        logger.info("Found existing bot message in chat: %s", text[:50])
                        return True

                    # Otherwise check if text matches
                    if search_lower in text.lower():
                        logger.info("Found bot message containing '%s': %s", search_text, text[:50])
                        return True

            if search_text:
                logger.debug("No bot messages found containing '%s'", search_text)
            else:
                logger.debug("No bot messages found in recent chat")
            return False

        except HttpError as e:
            logger.warning("YouTube API error checking bot messages: %s", e)
            return False
        except Exception as e:
            logger.exception("Error checking bot messages: %s", e)
            return False

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

                if text and published_at > self.chat_start_ts:  # Only include messages with actual text and published after the start of current stream iteration
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

    def get_stream_status(self, video_id: str) -> str | None:
        """
        Get the current status of a live stream.

        Args:
            video_id: The YouTube video ID of the live stream

        Returns:
            The stream status ('active', 'noData', etc.) or None if unavailable

        """
        try:
            # Get liveStream ID
            request = self.youtube.liveBroadcasts().list(part="id,snippet,contentDetails,status", id=video_id)
            response = request.execute()

            if response.get("items") and response["items"][0].get("contentDetails"):
                livestream_id = response["items"][0].get("contentDetails")["boundStreamId"]

                request = self.youtube.liveStreams().list(part="id,status", id=livestream_id)
                response = request.execute()

                status = response["items"][0]["status"].get("healthStatus")["status"]
                if status:
                    logger.debug("Stream status for %s: %s", video_id, status)
                    return status

            logger.warning("Stream status not found for video ID: %s", video_id)
            return None

        except HttpError as e:
            logger.exception("YouTube API HTTP error getting stream status: %s", e)
            return None
        except Exception as e:
            logger.exception("Error getting stream status: %s", e)
            return None
