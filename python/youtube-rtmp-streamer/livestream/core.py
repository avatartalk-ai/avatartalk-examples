import asyncio
import contextlib
import logging
import os
import random
import signal
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial

from openai import OpenAI

from livestream.avatartalk import AvatarTalkConnector
from livestream.chat_handler import ChatHandler
from livestream.config import (
    AVATARTALK_API_KEY,
    AVATARTALK_DEFAULT_BACKGROUND_URL,
    AVATARTALK_MODEL,
    AVATARTALK_TOPICS_FILE,
    AVATARTALK_TTS_PROVIDER,
    AVATARTALK_URL,
    YOUTUBE_API_KEY,
    YOUTUBE_RTMP_URL,
    YOUTUBE_STREAM_KEY,
)
from livestream.context_store import GlobalContextStore
from livestream.youtube import YouTubeCommentManager

logger = logging.getLogger(__name__)

SECONDS_UNTIL_REFRESH = 180
IDLE_WAIT_SECONDS = 10
MAX_IDLE_WAIT_SECONDS = 15
BUSY_WAIT_SECONDS = 5
LANGUAGE_MAP = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "nl": "Dutch",
    "cs": "Czech",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "hu": "Hungarian",
    "ko": "Korean",
    "hi": "Hindi",
}


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

    def __init__(
        self,
        live_id: str,
        language: str,
        voice_id: str,
        stream_key: str,
        avatar_name: str,
        background_url: str | None = None,
        skip_welcome: bool = False,
    ):
        logger.info("Initializing AvatarTalkStreamer...")
        logger.debug(
            "Parameters: live_id=%s, language=%s, voice_id=%s, avatar_name=%s, skip_welcome=%s",
            live_id,
            language,
            voice_id,
            avatar_name,
            skip_welcome,
        )

        logger.debug("Initializing OpenAI client...")
        self.client = self._init_openai_client()
        logger.debug("OpenAI client initialized")

        self.model = AVATARTALK_MODEL
        logger.debug("Using model: %s", self.model)

        self.topics_file = AVATARTALK_TOPICS_FILE
        self.shutdown_requested = False
        self._shutdown_event: asyncio.Event | None = None
        self.room_name = "avatartalk-live"
        self.youtube_live_id = live_id
        self.stream_language = language
        self.voice_id = voice_id
        # Cooldown lead time (seconds before current segment ends to start generating the next one)
        self.remaining_duration_to_play = 4
        self.stream_key = stream_key or YOUTUBE_STREAM_KEY
        self.avatar_name = avatar_name
        self.skip_welcome = skip_welcome
        # Track if we've waited for the welcome skip period
        self._welcome_skip_complete = not skip_welcome

        # Global context store - shared between chat and narration
        logger.debug("Initializing global context store...")
        self.context_store = GlobalContextStore(max_chat_messages=50, max_interactions=10)

        # Rolling context for avatar narration - keep last 2 segments only
        # Using deque with maxlen to prevent unbounded growth
        self.narration_history: deque = deque(maxlen=2)
        self.recent_topics: deque[str] = deque(maxlen=10)

        # Load topics
        logger.debug("Loading topics from %s...", self.topics_file)
        self.topics = self._load_topics()

        # System prompts - separate for chat and narration
        language_full = LANGUAGE_MAP.get(self.stream_language, "English")
        logger.debug("Language mapping: %s -> %s", self.stream_language, language_full)

        logger.debug("Loading narration system prompt...")
        self.narration_system_prompt = self._create_narration_system_prompt(language_full)
        logger.debug("Narration system prompt loaded")

        logger.debug("Initializing chat handler...")
        self.chat_handler = ChatHandler(
            self.client,
            self.model,
            self.context_store,
            language=language_full,
        )
        logger.debug("Chat handler initialized")

        # Set up YouTube comment manager (uses OAuth2 credentials; YOUTUBE_API_KEY is optional)
        logger.debug("Initializing YouTube comment manager...")
        self.youtube_manager = YouTubeCommentManager(YOUTUBE_API_KEY, openai_client=self.client)

        # Ensure we have a valid active/ready broadcast and RTMP stream key
        ensured_id, ensured_rtmp_url, ensured_stream_key = self.youtube_manager.ensure_live_broadcast(
            video_id=self.youtube_live_id,
            language=self.stream_language,
        )
        self.youtube_live_id = ensured_id
        self.rtmp_url = YOUTUBE_RTMP_URL or ensured_rtmp_url or "rtmp://a.rtmp.youtube.com/live2"
        self.stream_key = self.stream_key or ensured_stream_key

        logger.debug("Creating AvatarTalk connector...")
        self.avatartalk_connector = AvatarTalkConnector(
            url=AVATARTALK_URL,
            api_key=AVATARTALK_API_KEY,
            avatar=self.avatar_name,
            language=self.stream_language,
            rtmp_url=self.rtmp_url,
            stream_key=self.stream_key,
            background_url=background_url or AVATARTALK_DEFAULT_BACKGROUND_URL,
            tts_provider=AVATARTALK_TTS_PROVIDER,
        )
        logger.debug("AvatarTalk connector created")

        logger.debug("Setting up YouTube stream...")
        self._setup_youtube_stream()

        self.last_comment_check = time.time()
        self.last_connector_restart = time.time()

        # Dedicated single-thread executor for all YouTube API calls.
        # googleapiclient uses httplib2 internally which is NOT thread-safe;
        # serializing through one thread prevents concurrent access.
        self._yt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yt-api")

        logger.info("AvatarTalkStreamer initialization complete")

    def _init_openai_client(self) -> OpenAI:
        """Initialize OpenAI client with connection pool limits to prevent memory leaks."""
        import httpx

        # Configure httpx client with connection limits to prevent unbounded growth
        # This is critical when running multiple instances and making frequent API calls
        http_client = httpx.Client(
            limits=httpx.Limits(
                max_connections=100,  # Total connections across all hosts
                max_keepalive_connections=20,  # Connections to keep alive
                keepalive_expiry=30.0,  # Close idle connections after 30s
            ),
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        return OpenAI(http_client=http_client)

    async def close(self) -> None:
        """Clean up resources (OpenAI client, YouTube manager, AvatarTalk connector)."""
        logger.info("Closing AvatarTalkStreamer resources...")

        # Close OpenAI client
        try:
            if hasattr(self, "client") and self.client:
                self.client.close()
                logger.debug("OpenAI client closed")
        except Exception as e:
            logger.error("Error closing OpenAI client: %s", e)

        # Close YouTube manager
        try:
            if hasattr(self, "youtube_manager") and self.youtube_manager:
                await self.youtube_manager.close()
                logger.debug("YouTube manager closed")
        except Exception as e:
            logger.error("Error closing YouTube manager: %s", e)

        # Close AvatarTalk connector
        try:
            if hasattr(self, "avatartalk_connector") and self.avatartalk_connector:
                await self.avatartalk_connector.close()
                logger.debug("AvatarTalk connector closed")
        except Exception as e:
            logger.error("Error closing AvatarTalk connector: %s", e)

        # Shut down the YouTube API executor
        try:
            if hasattr(self, "_yt_executor") and self._yt_executor:
                self._yt_executor.shutdown(wait=False)
                logger.debug("YouTube API executor shut down")
        except Exception as e:
            logger.error("Error shutting down YouTube API executor: %s", e)

        logger.info("AvatarTalkStreamer resources closed")

    def _create_narration_system_prompt(self, language: str) -> str:
        """Create narration system prompt from template based on language."""
        try:
            with open("narration.prompt") as f:
                template = f.read()
            return template.replace("{language}", language)
        except FileNotFoundError:
            logger.critical("narration.prompt file not found")
            raise
        except Exception as e:
            logger.critical("Failed to load narration.prompt: %s", e)
            logger.exception("Full traceback:")
            raise

    def _setup_youtube_stream(self) -> str | None:
        """Setup YouTube live stream detection."""
        if not self.youtube_manager:
            logger.warning("YouTube manager not initialized")
            return None

        try:
            # Try to get live stream ID from environment or auto-detect
            live_id = self.youtube_live_id
            if not live_id:
                logger.info("No live ID provided, attempting auto-detection...")
                live_id = self.youtube_manager.find_live_stream(language=self.stream_language)
                if live_id:
                    logger.info("Auto-detected live stream ID: %s", live_id)

            if live_id:
                logger.debug("Getting live chat ID for stream: %s", live_id)
                live_chat_id = self.youtube_manager.get_live_chat_id(live_id)
                if live_chat_id:
                    logger.info("Successfully connected to live chat: %s", live_chat_id)
                    return live_chat_id
                logger.warning("Could not get live chat ID for stream %s", live_id)
                return None
            logger.warning("No live stream found, comment integration will be limited")
            return None
        except Exception as e:
            logger.error("Error setting up YouTube stream: %s", e)
            logger.exception("Full traceback:")
            # Don't raise - allow initialization to continue without YouTube integration
            return None

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

    def _pick_random_topic(self) -> str:
        """Pick a random topic avoiding recently used ones."""
        available = [t for t in self.topics if t not in self.recent_topics] or self.topics
        chosen = random.choice(available)
        self.recent_topics.append(chosen)
        return chosen

    def _create_user_prompt(self, topic: str) -> str:
        """Create user prompt for the given topic with concise word count."""
        word_count = random.randint(35, 50)
        language_name = LANGUAGE_MAP.get(self.stream_language, "English")
        return f"Produce ONE concise segment in {language_name} about: {topic}. Strictly {word_count} words max (3-4 short sentences). End with a quick question to the live chat."

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
        # deque already stores max 2 items, so just convert to list
        messages.extend(list(self.narration_history))

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
                model=self.model, messages=messages, max_tokens=120, temperature=0.8
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
        logger.warning("Received interrupt signal (signal %d). Initiating graceful shutdown...", signum)
        logger.info("Setting shutdown_requested flag to stop all loops")
        self.shutdown_requested = True
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        logger.info("Shutdown flag set. Waiting for tasks to complete...")

    async def _sleep_or_shutdown(self, seconds: float) -> bool:
        """Sleep for `seconds` or return True immediately if shutdown is requested."""
        if self.shutdown_requested:
            return True
        if self._shutdown_event is None:
            await asyncio.sleep(seconds)
            return self.shutdown_requested
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=max(0.0, seconds))
        return self.shutdown_requested

    async def _play_segment(self, segment: str) -> float:
        """Send the segment to the connector and return audio duration (seconds)."""
        # Output segment to stdout (used by TTS pipeline)
        print(segment)
        print()

        logger.debug("Sending segment and waiting for response from AvatarTalk API...")
        audio_info = await self.avatartalk_connector.send_and_receive(segment)
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
        iteration = 1

        wait_time = BUSY_WAIT_SECONDS

        while not self.shutdown_requested:
            try:
                if not self.youtube_manager.live_chat_id:
                    await loop.run_in_executor(self._yt_executor, self._setup_youtube_stream)
                    if not self.youtube_manager.live_chat_id:
                        logger.warning(f"Still not able to get Live Chat ID, waiting {IDLE_WAIT_SECONDS}")
                        if await self._sleep_or_shutdown(IDLE_WAIT_SECONDS):
                            break
                        continue

                if await self._sleep_or_shutdown(wait_time):
                    break
                logger.debug("Chat loop: fetching comments (polling interval: %.2fs)...", wait_time)

                # Run blocking YouTube API call in dedicated executor with timeout
                try:
                    comments = await asyncio.wait_for(
                        loop.run_in_executor(self._yt_executor, self.youtube_manager.get_recent_comments),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.warning("Chat loop: get_recent_comments() timed out after 10s")
                    continue

                # Use YouTube's recommended polling interval, but respect our minimums
                youtube_poll_seconds = self.youtube_manager.polling_interval_ms / 1000.0

                if not comments:
                    logger.debug("Chat loop: no new comments")
                    iteration += 1
                    if iteration >= 30:
                        wait_time = max(youtube_poll_seconds, MAX_IDLE_WAIT_SECONDS)
                    elif iteration >= 6:
                        wait_time = max(youtube_poll_seconds, IDLE_WAIT_SECONDS)
                    if (
                        iteration * IDLE_WAIT_SECONDS >= SECONDS_UNTIL_REFRESH
                        and self.chat_handler.context_store.get_recent_chat_messages(count=1)
                    ):
                        logger.info(
                            "No chat messages for %d seconds, clearing context store",
                            SECONDS_UNTIL_REFRESH,
                        )
                        self.chat_handler.context_store.clear()
                    continue

                logger.info("Processing %d new comments in chat loop (batched)", len(comments))
                iteration = 0
                wait_time = max(youtube_poll_seconds, BUSY_WAIT_SECONDS)
                logger.info(f"Polling interval: {wait_time:.2f}s")

                # Process all new comments as a single batch so the chat queue never grows
                try:
                    response = await self.chat_handler.process_comments_batch(comments)

                    if response:
                        logger.info("Sending chat response: %s", response[:100])
                        try:
                            await asyncio.wait_for(
                                loop.run_in_executor(
                                    self._yt_executor, self.youtube_manager.send_chat_message, response
                                ),
                                timeout=10.0,
                            )
                            logger.debug("Chat response sent successfully")
                        except TimeoutError:
                            logger.warning("Chat loop: send_chat_message() timed out after 10s")
                        except Exception as e:
                            logger.exception("Failed to send chat message: %s", e)
                except Exception as e:
                    logger.exception("Error processing comment batch: %s", e)

            except KeyboardInterrupt:
                logger.info("Chat loop interrupted by user")
                break
            except Exception as e:
                logger.exception("Error in chat loop: %s", e)
                # Don't break on recoverable errors - continue monitoring
                # Only fatal errors (auth, config) should break
                await asyncio.sleep(5)  # Brief pause before retrying
                continue

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

        # Auto-detect if welcome messages were already sent, or use explicit skip flag
        loop = asyncio.get_event_loop()
        should_skip_welcome = self.skip_welcome

        if not self._welcome_skip_complete:
            # Check if the bot has already posted ANY messages to the chat
            # If so, this is likely a stream restart and we should skip the welcome
            try:
                logger.info("Checking if bot has already posted messages to chat...")

                has_posted = await loop.run_in_executor(
                    self._yt_executor,
                    partial(self.youtube_manager.check_for_bot_messages, search_text=None, max_messages=30),
                )

                if has_posted:
                    logger.info("Detected existing bot messages in chat - this is a stream restart, skipping welcome")
                    should_skip_welcome = True
                    self._welcome_skip_complete = True
                else:
                    logger.info("No bot messages found - this appears to be a fresh stream start")

            except Exception as e:
                logger.warning("Could not check for existing bot messages: %s", e)
                # Continue with original skip_welcome setting

        # If skip_welcome is enabled (explicit or auto-detected), wait before generating first segment
        if should_skip_welcome and not self._welcome_skip_complete:
            logger.info("Skip welcome mode: waiting 60 seconds before starting narration...")
            if await self._sleep_or_shutdown(60):
                return
            self._welcome_skip_complete = True
            logger.info("Welcome skip period complete, starting narration")

        # Track monotonic time when current queued audio playback finishes on the server
        playback_ends_at = time.monotonic()
        last_narrated_message_ts: datetime | None = None

        while not self.shutdown_requested:
            if self.avatartalk_connector.reconnected_event:
                logger.info("WebSocket reconnected — resetting playback schedule to play immediately")
                self.avatartalk_connector.reconnected_event = False
                playback_ends_at = time.monotonic()

            now = time.monotonic()
            remaining_playback = max(0.0, playback_ends_at - now)
            if remaining_playback > self.remaining_duration_to_play:
                wait_for = min(2.0, remaining_playback - self.remaining_duration_to_play)
                if await self._sleep_or_shutdown(wait_for):
                    break
                continue

            try:
                recent_messages = self.context_store.get_recent_chat_messages(count=10)

                unseen_messages = [
                    msg
                    for msg in recent_messages
                    if (last_narrated_message_ts is None or msg.timestamp > last_narrated_message_ts)
                    and (datetime.now(UTC) - msg.timestamp).total_seconds() < SECONDS_UNTIL_REFRESH
                ]

                # If we have new, unnarrated chat activity, generate a topic from it once
                if unseen_messages:
                    last_narrated_message_ts = unseen_messages[-1].timestamp
                    try:
                        topic = await loop.run_in_executor(
                            self._yt_executor,
                            self.youtube_manager.summarize_comments,
                            [{"author": msg.author, "text": msg.text} for msg in unseen_messages[-5:]],
                        )
                        logger.info("Using topic from new chat messages: %s", topic)
                    except Exception:
                        logger.warning("Failed to summarize recent chat, using random topic")
                        topic = self._pick_random_topic()
                else:
                    # No new unnarrated chat messages, pick a fresh random topic
                    topic = self._pick_random_topic()
                    logger.info("No new chat messages since last narration, using topic: %s", topic)

                segment = await loop.run_in_executor(None, self._generate_segment, topic)

                if not segment:
                    logger.warning("Segment generation failed; retrying soon...")
                    if await self._sleep_or_shutdown(3.0):
                        break
                    continue

                duration = await self._play_segment(segment)
                now_after_send = time.monotonic()
                if self.avatartalk_connector.reconnected_event:
                    self.avatartalk_connector.reconnected_event = False
                    playback_ends_at = now_after_send + duration
                else:
                    playback_ends_at = max(now_after_send, playback_ends_at) + duration

            except KeyboardInterrupt:
                logger.info("Narration loop interrupted")
                break
            except RuntimeError as e:
                # RuntimeError from websocket reconnection failures
                # The connector has already tried to reconnect, so we just log and continue
                logger.exception("WebSocket error in narration loop: %s", e)
                logger.info("Waiting 10 seconds before retrying narration...")
                await asyncio.sleep(10)
                continue
            except Exception as e:
                logger.exception("Error in narration loop: %s", e)
                # Don't break - allow loop to continue with next segment
                # The websocket auto-reconnection will handle connection issues
                await asyncio.sleep(5)
                continue

        logger.info("Narration loop stopped")

    async def _healthcheck_loop(self) -> None:
        """
        Health check loop for monitoring YouTube stream status.

        Periodically checks if the stream status is 'noData' and restarts
        the AvatarTalk connector if needed. Waits 60 seconds after each
        connector restart before checking again to allow time for the
        stream to stabilize.
        """
        logger.info("Healthcheck loop started")

        loop = asyncio.get_event_loop()
        check_interval = 45  # Check every 45 seconds to conserve YouTube API quota
        restart_cooldown = 60  # Wait 60 seconds after restart before checking again

        _iteration = 0
        while not self.shutdown_requested:
            try:
                # Wait for the check interval
                if await self._sleep_or_shutdown(check_interval):
                    break

                # Check if we're still in cooldown period after a restart
                time_since_restart = time.time() - self.last_connector_restart
                if time_since_restart < restart_cooldown:
                    remaining = restart_cooldown - time_since_restart
                    logger.debug("Healthcheck: in cooldown period, %.1f seconds remaining", remaining)
                    continue

                # Check stream status (run in dedicated executor to avoid blocking)
                try:
                    status = await asyncio.wait_for(
                        loop.run_in_executor(self._yt_executor, self.youtube_manager.get_stream_status, self.youtube_live_id),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.warning("Healthcheck: get_stream_status() timed out after 10s")
                    continue

                if status == "noData":
                    _iteration += 1
                    logger.warning("Healthcheck: Stream status is 'noData' (iteration %d/5)", _iteration)
                    if _iteration >= 5:
                        logger.warning(
                            "Healthcheck: Stream status 'noData' persisted for 5 checks, restarting AvatarTalk connector"
                        )
                        if await self.avatartalk_connector.restart():
                            logger.info("Healthcheck: Successfully restarted connector")
                            self.last_connector_restart = time.time()
                        else:
                            logger.error("Healthcheck: Failed to restart connector; will retry later")
                        _iteration = 0
                else:
                    if _iteration > 0:
                        logger.info("Healthcheck: Stream status recovered to '%s', resetting counter", status)
                    _iteration = 0
                    logger.debug("Healthcheck: Stream status is '%s' (OK)", status)

            except Exception as e:
                logger.exception("Error in healthcheck loop: %s", e)
                # Don't break - continue monitoring
                await asyncio.sleep(check_interval)

        logger.info("Healthcheck loop stopped")

    async def run_async(self) -> None:
        """
        Async main loop - runs two concurrent tasks:
        1. Chat handler - responds to questions immediately
        2. Avatar narration - generates topic-based segments with full context
        """
        try:
            self._shutdown_event = asyncio.Event()
            logger.info("Initializing AvatarTalk connector...")
            await self.avatartalk_connector.initialize()
            logger.info("AvatarTalk connector initialized successfully")

            signal.signal(signal.SIGINT, self._handle_interrupt)

            logger.info("AvatarTalk Teacher starting with model: %s", self.model)
            logger.info("Press Ctrl+C to stop")
            if self.youtube_manager:
                logger.info("YouTube comment integration: ENABLED")
                logger.info("Chat handling: ENABLED (separate thread)")
                logger.info("Avatar narration: ENABLED (with context awareness)")
                logger.info("Stream health monitoring: ENABLED")

            # Run chat, narration, and healthcheck loops concurrently
            logger.info("Starting concurrent task loops...")
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._chat_loop(), name="chat_loop")
                    tg.create_task(self._narration_loop(), name="narration_loop")
                    tg.create_task(self._healthcheck_loop(), name="healthcheck_loop")
                    logger.info("Created tasks: chat_loop, narration_loop, healthcheck_loop")

                logger.info("All tasks completed normally")

            except* Exception as eg:
                # Handle ExceptionGroup from TaskGroup - this catches exceptions from any of the tasks
                logger.critical("One or more tasks failed with exceptions:")
                for i, exc in enumerate(eg.exceptions, 1):
                    logger.critical("Exception %d/%d: %s: %s", i, len(eg.exceptions), type(exc).__name__, exc)
                    logger.exception("Full traceback for exception %d:", i, exc_info=exc)

                # Re-raise to propagate the failure
                raise

        except KeyboardInterrupt:
            logger.info("AvatarTalk Teacher stopped by user (Ctrl+C). Thanks for listening!")
        except BaseException as e:
            # Catch ExceptionGroup and any other exceptions
            logger.critical("Fatal error during run_async: %s: %s", type(e).__name__, e)
            logger.exception("Full traceback:")
            raise
        finally:
            logger.info("Cleaning up resources...")
            try:
                await self.close()
                logger.info("All resources closed successfully")
            except Exception as e:
                logger.error("Error during cleanup: %s", e)
                logger.exception("Full traceback:")

    def run(self) -> None:
        """Main entry point - handles both sync and async components."""
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(self.run_async())
