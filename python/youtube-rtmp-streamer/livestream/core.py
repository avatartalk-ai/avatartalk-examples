import asyncio
import contextlib
import json
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

THEME_DOMAINS = (
    "Workplace & leadership situations (pushing back on deadlines, giving tough feedback, running crisp meetings, salary & career talks)",
    "Everyday social life & travel (hotels, airports, restaurants, making friends abroad, small talk that isn't boring, graceful exits)",
    "Sales, client relations & negotiations (handling objections, building trust, following up without being annoying, setting boundaries)",
    "Idioms, phrasal verbs & colorful native expressions people use in daily conversation",
    "Cultural & tone nuances (British vs American understatement, sounding polite vs passive-aggressive, softening direct requests)",
    "Modern digital communication (Slack, emails, voice notes, video calls — sounding warm and sharp instead of stiff or robotic)",
    "Pronunciation, word stress & rhythm secrets that instantly make spoken English sound more natural",
    "Storytelling, humor, and thinking on your feet when you get an unexpected question",
)

ARC_STEPS = (
    "Part 1 of 4 (Introduce the Theme): Open a new mini-chapter. Set up a relatable real-life situation for this theme and teach the first natural phrase or core insight.",
    "Part 2 of 4 (Common Mistake vs Upgrade): Stay on the EXACT same theme! Contrast a stiff, textbook, or awkward phrase people often use in this situation with what fluent speakers actually say.",
    "Part 3 of 4 (Nuance, Mini-Dialogue, or Idiom): Stay on the EXACT same theme! Go one layer deeper—share a vivid mini-example, a tone nuance, or a great idiom that fits this exact situation.",
    "Part 4 of 4 (Wrap-Up & Audience Question): Conclude this mini-chapter with a final practical takeaway and ask a natural question inviting viewers in the live chat to share how they handle it.",
)


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

        self.shutdown_requested = False
        self._shutdown_event: asyncio.Event | None = None
        self.room_name = "avatartalk-live"
        self.youtube_live_id = live_id
        self.stream_language = language
        self.voice_id = voice_id
        self.stream_key = stream_key or YOUTUBE_STREAM_KEY
        self.avatar_name = avatar_name
        self.skip_welcome = skip_welcome
        # Track if we've waited for the welcome skip period
        self._welcome_skip_complete = not skip_welcome

        # Global context store - shared between chat and narration
        logger.debug("Initializing global context store...")
        self.context_store = GlobalContextStore(max_chat_messages=50, max_interactions=10)

        # Rolling context for avatar narration:
        # - narration_history keeps the last 8 spoken segments so sentence rhythm & openings stay varied
        # - covered_topics keeps the last 150 topic summaries (>1 hour of streaming) so the agent never loops
        self.narration_history: deque = deque(maxlen=8)
        self.covered_topics: deque[str] = deque(maxlen=150)
        self._segment_counter = 0
        self._arc_step = 0
        self._theme_index = 0
        self.current_theme: str | None = None

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
        self.last_segment_sent_at = time.time()

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

    def _create_user_prompt(self, chat_topic_hint: str | None = None) -> str:
        """Create dynamic user prompt that develops a cohesive 4-part theme before moving to a new one."""
        word_count = random.randint(28, 36)
        language_name = LANGUAGE_MAP.get(self.stream_language, "English")
        include_cta = (self._segment_counter % 8) == 7
        self._segment_counter += 1

        covered_list = list(self.covered_topics)
        covered_block = (
            "Previously covered themes & sub-points (DO NOT repeat any of these concepts, words, idioms, or scenarios):\n- "
            + "\n- ".join(covered_list[-80:])
            if covered_list
            else "No topics covered yet in this session."
        )

        cta_instruction = (
            "At the end of this segment, casually mention that viewers can practice 1-on-1 live voice role-play at avatartalk.ai/ai-training."
            if include_cta
            else "Do NOT mention avatartalk.ai in this segment; focus 100% on the conversation and language insight."
        )

        if chat_topic_hint:
            self.current_theme = f"Viewer chat topic: {chat_topic_hint}"
            self._arc_step = 1
            focus_instruction = (
                f"Viewers in the live chat just brought up: {chat_topic_hint}.\n"
                f"Make this our current theme! Respond to it warmly and teach a practical {language_name} insight around it."
            )
        elif self._arc_step == 0 or not self.current_theme:
            domain = THEME_DOMAINS[self._theme_index % len(THEME_DOMAINS)]
            self._theme_index += 1
            step_instruction = ARC_STEPS[0]
            self._arc_step = 1
            focus_instruction = (
                f"Domain for this new 4-part mini-chapter: {domain}\n"
                f"{step_instruction}\n"
                f"Choose a specific, fresh overarching 'theme' in {language_name} that is NOT in the previously covered list. "
                "If you were talking about something else right before this, use a smooth 3–5 word bridge into this new theme."
            )
        else:
            step_instruction = ARC_STEPS[self._arc_step]
            self._arc_step = (self._arc_step + 1) % len(ARC_STEPS)
            focus_instruction = (
                f"Current overarching theme (STAY ON THIS THEME): {self.current_theme}\n"
                f"{step_instruction}\n"
                "Connect naturally to what you just said in the previous segment so it feels like one continuous, thoughtful explanation."
            )

        return (
            f"{covered_block}\n\n"
            f"{focus_instruction}\n"
            f"{cta_instruction}\n"
            f"Target length for 'segment': ~{word_count} words (2–3 natural sentences in {language_name}).\n"
            'Return JSON: {"theme": "<current overarching theme>", "topic": "<specific 5-10 word sub-point taught in this segment>", "segment": "<spoken text>"}'
        )

    def _build_messages(self, user_prompt: str) -> list[dict[str, str]]:
        """
        Build message list for avatar narration.

        Includes:
        - System prompt (avatar as autonomous coach)
        - Recent chat context from global store
        - Last 8 narration segments for continuity and stylistic variety
        - Current user prompt (with covered-topic memory and angle)
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

        # Add recent narration segments for continuity and to avoid repeating sentence openings
        messages.extend(list(self.narration_history))

        # Add current user prompt
        messages.append({"role": "user", "content": user_prompt})

        return messages

    def _generate_segment(self, chat_topic_hint: str | None = None) -> str | None:
        """
        Autonomously choose a fresh topic and generate the next narration segment.

        Stores the generated topic summary in `self.covered_topics` so the stream
        never loops on the same ideas over multi-hour runs.
        """
        user_prompt = self._create_user_prompt(chat_topic_hint)
        messages = self._build_messages(user_prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=200,
                temperature=0.85,
                response_format={"type": "json_object"},
            )

            raw_content = response.choices[0].message.content.strip()
            theme_name = ""
            topic_summary = ""
            segment = raw_content
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict):
                    theme_name = str(parsed.get("theme") or "").strip()
                    topic_summary = str(parsed.get("topic") or "").strip()
                    segment = str(parsed.get("segment") or "").strip()
            except json.JSONDecodeError:
                logger.warning("Model did not return valid JSON; using raw content as segment")

            if not segment:
                return None

            if theme_name:
                self.current_theme = theme_name

            if topic_summary:
                entry = f"{self.current_theme} — {topic_summary}" if self.current_theme else topic_summary
                self.covered_topics.append(entry)
                logger.info(
                    "Agent segment (#%d, step=%d/4, memory=%d): [%s] %s",
                    self._segment_counter,
                    ((self._arc_step - 1) % 4) + 1,
                    len(self.covered_topics),
                    self.current_theme or "general",
                    topic_summary,
                )
            else:
                self.covered_topics.append(segment[:60])

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
        """Send a segment to the connector, print it as playback starts, and return duration (seconds)."""
        logger.debug("Sending segment and waiting for response from AvatarTalk API...")
        audio_info = await self.avatartalk_connector.send_and_receive(segment)
        duration = float(audio_info.get("audio_duration", 0.0))
        self.last_segment_sent_at = time.time()

        # Output segment to stdout once synthesis is complete and playback begins
        print(segment, flush=True)
        print(flush=True)

        logger.info("Segment duration: %.2fs (includes %.1fs pause)", duration, self.avatartalk_connector.silence_duration)
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
        generation_lead_seconds = 5.0
        send_lead_seconds = 1.8
        first_chunk_startup_offset = 3.5

        while not self.shutdown_requested:
            now = time.monotonic()
            remaining_playback = max(0.0, playback_ends_at - now)
            if remaining_playback > generation_lead_seconds:
                wait_for = min(1.0, remaining_playback - generation_lead_seconds)
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

                # If we have new, unnarrated chat activity, summarize it as a hint for the agent
                chat_topic_hint: str | None = None
                if unseen_messages:
                    last_narrated_message_ts = unseen_messages[-1].timestamp
                    try:
                        chat_topic_hint = await loop.run_in_executor(
                            self._yt_executor,
                            self.youtube_manager.summarize_comments,
                            [{"author": msg.author, "text": msg.text} for msg in unseen_messages[-5:]],
                        )
                        logger.info("Using topic hint from new chat messages: %s", chat_topic_hint)
                    except Exception:
                        logger.warning("Failed to summarize recent chat, agent will pick topic autonomously")

                segment = await loop.run_in_executor(None, self._generate_segment, chat_topic_hint)

                if not segment:
                    logger.warning("Segment generation failed; retrying soon...")
                    if await self._sleep_or_shutdown(3.0):
                        break
                    continue

                # Wait until previous segment (including its 2.0s pause) is within `send_lead_seconds` of finishing
                while not self.shutdown_requested:
                    rem = playback_ends_at - time.monotonic()
                    if rem <= send_lead_seconds:
                        break
                    if await self._sleep_or_shutdown(min(0.5, rem - send_lead_seconds)):
                        break
                if self.shutdown_requested:
                    break

                duration = await self._play_segment(segment)
                now_after_send = time.monotonic()
                if self.avatartalk_connector.first_chunk_on_ws or self.avatartalk_connector.reconnected_event:
                    self.avatartalk_connector.first_chunk_on_ws = False
                    self.avatartalk_connector.reconnected_event = False
                    playback_ends_at = max(now_after_send, playback_ends_at) + duration + first_chunk_startup_offset
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

                # If the narration loop recently sent a chunk and received a valid duration response,
                # the WebSocket/RTMP pipeline is actively streaming. Skip YouTube status polling to
                # avoid false-positive 'noData' restarts between non-realtime ffmpeg frame batches.
                since_last_segment = time.time() - self.last_segment_sent_at
                if since_last_segment < 35.0:
                    if _iteration > 0:
                        logger.info("Healthcheck: Narration pipeline active, resetting counter")
                        _iteration = 0
                    logger.debug("Healthcheck: Narration pipeline active (last chunk %.1fs ago)", since_last_segment)
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
                    # Re-check after 5s to avoid false positives during brief inter-chunk pauses
                    if await self._sleep_or_shutdown(5.0):
                        break
                    with contextlib.suppress(TimeoutError):
                        status = await asyncio.wait_for(
                            loop.run_in_executor(
                                self._yt_executor, self.youtube_manager.get_stream_status, self.youtube_live_id
                            ),
                            timeout=10.0,
                        )
                if status == "noData":
                    _iteration += 1
                    logger.warning("Healthcheck: Stream status is 'noData' (iteration %d/6)", _iteration)
                    if _iteration >= 6:
                        logger.warning(
                            "Healthcheck: Stream status 'noData' persisted for 6 checks, restarting AvatarTalk connector"
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
