import asyncio
import contextlib
import logging
import os
import random
import signal
import sys
import time
from datetime import UTC, datetime

from openai import OpenAI

from livestream.avatartalk import AvatarTalkConnector
from livestream.chat_handler import ChatHandler
from livestream.config import (
    AVATARTALK_API_KEY,
    AVATARTALK_AVATAR,
    AVATARTALK_DEFAULT_BACKGROUND_URL,
    AVATARTALK_MODEL,
    AVATARTALK_PROMPT_PATH,
    AVATARTALK_TOPICS_FILE,
    AVATARTALK_URL,
    YOUTUBE_API_KEY,
    YOUTUBE_RTMP_URL,
    YOUTUBE_STREAM_KEY,
)
from livestream.context_store import GlobalContextStore
from livestream.youtube import YouTubeCommentManager

logger = logging.getLogger(__name__)

SECONDS_UNTIL_REFRESH = 180


class AvatarTalkStreamer:
    """
    Coordinates topic selection, text generation, and streaming.

    This class now separates two main functions:
    1. Chat handling - Direct Q&A with viewers (runs independently)
    2. Avatar narration - Higher-level commentary that observes both
       the chat interactions and the ongoing conversation

    Both use a shared GlobalContextStore to maintain awareness of
    what's happening in the stream.
    """

    def __init__(self, live_id: str, language: str, background_url: str | None = None):
        self.client = self._init_openai_client()
        self.model = AVATARTALK_MODEL
        self.topics_file = AVATARTALK_TOPICS_FILE
        self.shutdown_requested = False
        self.room_name = "avatartalk-live"
        self.youtube_live_id = live_id
        self.stream_language = language
        # Cooldown to avoid overlapping segments while previous audio plays
        self.remaining_duration_to_play = 10
        self.prompt_path = AVATARTALK_PROMPT_PATH

        # Global context store - shared between chat and narration
        self.context_store = GlobalContextStore(max_chat_messages=50, max_interactions=10)

        # Rolling context for avatar narration - keep last 2 segments
        self.narration_history: list[dict] = []

        # Load topics
        self.topics = self._load_topics()
        self.avatartalk_connector = AvatarTalkConnector(
            AVATARTALK_URL,
            AVATARTALK_API_KEY,
            AVATARTALK_AVATAR,
            self.stream_language,
            YOUTUBE_RTMP_URL,
            YOUTUBE_STREAM_KEY,
            background_url or AVATARTALK_DEFAULT_BACKGROUND_URL,
        )

        # System prompts - separate for chat and narration
        with open(self.prompt_path) as f:
            self.narration_system_prompt = f.read()

        # Chat handler for direct Q&A
        chat_system_prompt = (
            "You are a helpful AI assistant responding to questions in a YouTube Live chat. "
            "Keep your responses concise (2-3 sentences max) and friendly. "
            "An avatar narrator is also discussing topics on the stream - you work together "
            "but handle different aspects: you respond directly to viewer questions, while "
            "the avatar provides higher-level commentary."
        )
        self.chat_handler = ChatHandler(self.client, self.model, self.context_store, chat_system_prompt)

        # Set up YouTube comment manager
        youtube_api_key = YOUTUBE_API_KEY
        if youtube_api_key:
            self.youtube_manager = YouTubeCommentManager(youtube_api_key)
            self._setup_youtube_stream()
        else:
            logger.critical("YOUTUBE_API_KEY not provided")
            sys.exit(1)

        self.last_comment_check = time.time()

    def _init_openai_client(self) -> OpenAI:
        return OpenAI()

    def _setup_youtube_stream(self) -> None:
        """Setup YouTube live stream detection."""
        if not self.youtube_manager:
            return

        # Try to get live stream ID from environment or auto-detect
        live_id = self.youtube_live_id
        if not live_id:
            live_id = self.youtube_manager.find_live_stream()

        if live_id:
            self.youtube_manager.get_live_chat_id(live_id)
        else:
            logger.warning("No live stream found, comment integration will be limited")

    def _load_topics(self) -> list[str]:
        """Load topics from file - file must exist."""
        if not os.path.exists(self.topics_file):
            logger.critical("Topics file %s not found", self.topics_file)
            sys.exit(1)

        try:
            with open(self.topics_file, encoding="utf-8") as f:
                topics = [line.strip() for line in f if line.strip()]
            if not topics:
                logger.critical("No topics found in %s", self.topics_file)
                sys.exit(1)
            logger.info("Loaded %d topics from %s", len(topics), self.topics_file)
            return topics
        except Exception as e:
            logger.exception("Could not read %s: %s", self.topics_file, e)
            sys.exit(1)

    def _create_user_prompt(self, topic: str) -> str:
        """Create user prompt for the given topic with randomized word count."""
        word_count = random.randint(60, 90)
        return f"Produce ONE continuous segment in English about: {topic}. Aim for ~{word_count} words. End with a single-sentence question to the live chat."

    def _build_messages(self, user_prompt: str) -> list[dict[str, str]]:
        """
        Build message list for avatar narration.

        Includes:
        - System prompt (avatar as higher-level observer)
        - Recent chat context from global store
        - Last 2 narration segments for continuity
        - Current user prompt (topic)
        """
        messages = [{"role": "system", "content": self.narration_system_prompt}]

        # Add context from global store
        context_summary = self.context_store.get_context_summary()
        if context_summary and context_summary != "No recent context available.":
            messages.append(
                {
                    "role": "system",
                    "content": f"Current stream context (viewer chat + Q&A):\n{context_summary}",
                }
            )

        # Add last 2 narration segments for continuity
        messages.extend(self.narration_history[-2:])

        # Add current user prompt
        messages.append({"role": "user", "content": user_prompt})

        return messages

    def _generate_segment(self, topic: str) -> str | None:
        """
        Generate a single narration segment for the avatar.

        The avatar acts as a higher-level observer, aware of both
        the topic and the ongoing chat interactions.
        """
        user_prompt = self._create_user_prompt(topic)
        messages = self._build_messages(user_prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=200, temperature=0.8
            )

            segment = response.choices[0].message.content.strip()

            # Update rolling context with the new narration segment
            self.narration_history.append({"role": "assistant", "content": segment})

            return segment

        except Exception as e:
            logger.exception("OpenAI API error: %s", e)
            return None

    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        logger.info("Stopping AvatarTalk Teacher...")
        self.shutdown_requested = True

    async def _play_segment(self, segment: str) -> float:
        """Send the segment to the connector and return audio duration (seconds)."""
        # Output segment to stdout (used by TTS pipeline)
        print(segment)
        print()

        await self.avatartalk_connector.send(segment)
        logger.debug("Waiting for response from AvatarTalk API...")
        audio_info = await self.avatartalk_connector.receive()
        duration = float(audio_info.get("audio_duration", 0.0))
        logger.info("Segment duration: %.2fs", duration)
        return duration

    async def _chat_loop(self) -> None:
        """
        Independent chat handling loop.

        Continuously monitors for new comments and responds to questions
        immediately, without waiting for avatar narration segments.

        All YouTube API calls are wrapped in run_in_executor to prevent
        blocking the async event loop.

        Uses dynamic polling interval from YouTube API (pollingIntervalMillis)
        which tells us how often we should check for new messages.
        """
        logger.info("Chat loop started")

        loop = asyncio.get_event_loop()
        iteration = 0

        while not self.shutdown_requested:
            try:
                iteration += 1

                if iteration % 30 == 0:
                    logger.debug("Chat loop heartbeat (iteration %d)", iteration)

                # Use YouTube's recommended polling interval (in milliseconds)
                polling_delay = self.youtube_manager.polling_interval_ms / 1000.0
                await asyncio.sleep(polling_delay)
                logger.debug("Chat loop: fetching comments (polling interval: %.2fs)...", polling_delay)

                # Run blocking YouTube API call in executor with timeout
                try:
                    comments = await asyncio.wait_for(
                        loop.run_in_executor(None, self.youtube_manager.get_recent_comments),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.warning("Chat loop: get_recent_comments() timed out after 10s")
                    continue

                if not comments:
                    logger.debug("Chat loop: no new comments")
                    continue

                logger.info("Processing %d new comments in chat loop", len(comments))

                # Process each comment
                for comment in comments:
                    try:
                        response = await self.chat_handler.process_comment(comment)

                        if response:
                            logger.info("Sending chat response: %s", response[:100])
                            try:
                                await asyncio.wait_for(
                                    loop.run_in_executor(None, self.youtube_manager.send_chat_message, response),
                                    timeout=10.0,
                                )
                                logger.debug("Chat response sent successfully")
                            except TimeoutError:
                                logger.warning("Chat loop: send_chat_message() timed out after 10s")
                            except Exception as e:
                                logger.exception("Failed to send chat message: %s", e)
                    except Exception as e:
                        logger.exception("Error processing comment: %s", e)

            except Exception as e:
                logger.exception("Error in chat loop: %s", e)
                await asyncio.sleep(5)

        logger.info("Chat loop stopped")

    async def _narration_loop(self) -> None:
        """
        Avatar narration loop.

        Generates topic-based segments that observe the stream context,
        including recent chat interactions and Q&A history from the global store.

        Note: Does NOT poll YouTube comments directly - relies on chat loop
        to populate the global context store.

        All blocking calls (OpenAI summarization) are wrapped in run_in_executor
        to prevent blocking the async event loop.
        """
        logger.info("Narration loop started")

        loop = asyncio.get_event_loop()
        cooldown_remaining = 0.0

        while not self.shutdown_requested:
            if cooldown_remaining >= self.remaining_duration_to_play:
                await asyncio.sleep(1)
                cooldown_remaining -= 1
                continue

            try:
                start_processing = time.time()

                recent_messages = self.context_store.get_recent_chat_messages(count=10)

                chat_is_fresh = False
                if recent_messages:
                    # Check the timestamp of the most recent message
                    latest_message = recent_messages[-1]
                    time_since_last_message = (datetime.now(UTC) - latest_message.timestamp).total_seconds()
                    chat_is_fresh = time_since_last_message < SECONDS_UNTIL_REFRESH  # 3 minutes

                    if not chat_is_fresh:
                        logger.info(
                            "Last chat message was %.1f minutes ago, using random topic", time_since_last_message / 60
                        )

                # If we have fresh chat activity, try to generate a topic from it
                if chat_is_fresh:
                    # Create a summary of recent messages for topic selection
                    try:
                        topic = await loop.run_in_executor(
                            None,
                            self.youtube_manager.summarize_comments,
                            [{"author": msg.author, "text": msg.text} for msg in recent_messages[-5:]],
                        )
                        logger.info("Using topic from recent chat context: %s", topic)
                    except Exception:
                        logger.warning("Failed to summarize recent chat, using random topic")
                        topic = random.choice(self.topics)
                else:
                    # No recent chat activity or chat is stale, use random topic
                    topic = random.choice(self.topics)
                    logger.info("No fresh chat activity, using random topic: %s", topic)

                segment = await loop.run_in_executor(None, self._generate_segment, topic)

                text_generation_time = time.time() - start_processing

                if not segment:
                    logger.warning("Segment generation failed; retrying soon...")
                    await asyncio.sleep(3.0)
                    continue

                duration = await self._play_segment(segment)
                cooldown_remaining += duration - text_generation_time

            except KeyboardInterrupt:
                logger.info("Narration loop interrupted")
                break
            except Exception as e:
                logger.exception("Error in narration loop: %s", e)
                await asyncio.sleep(3.0)

        logger.info("Narration loop stopped")

    async def run_async(self) -> None:
        """
        Async main loop - runs two concurrent tasks:
        1. Chat handler - responds to questions immediately
        2. Avatar narration - generates topic-based segments with full context
        """
        try:
            await self.avatartalk_connector.initialize()

            signal.signal(signal.SIGINT, self._handle_interrupt)

            logger.info("AvatarTalk Teacher starting with model: %s", self.model)
            logger.info("Press Ctrl+C to stop")
            if self.youtube_manager:
                logger.info("YouTube comment integration: ENABLED")
                logger.info("Chat handling: ENABLED (separate thread)")
                logger.info("Avatar narration: ENABLED (with context awareness)")

            # Run chat and narration loops concurrently
            await asyncio.gather(
                self._chat_loop(),
                self._narration_loop(),
                return_exceptions=True,
            )

        except KeyboardInterrupt:
            logger.info("AvatarTalk Teacher stopped. Thanks for listening!")
        except Exception as e:
            logger.exception("Unexpected error during run: %s", e)
        finally:
            with contextlib.suppress(Exception):
                await self.avatartalk_connector.close()

    def run(self) -> None:
        """Main entry point - handles both sync and async components."""
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(self.run_async())
