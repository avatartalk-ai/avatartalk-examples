import asyncio
import contextlib
import json
import logging
import math

import random
import signal

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


)
from livestream.context_store import GlobalContextStore
from livestream.pacing import NarrationPacer
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
        live_id: str | None,
        language: str,
        voice_id: str,

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
        self.rtmp_url, self.stream_key = self._select_ingestion(ensured_rtmp_url, ensured_stream_key)
        logger.info("Selected YouTube broadcast: https://www.youtube.com/watch?v=%s", self.youtube_live_id)

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

    @staticmethod
    def _select_ingestion(bound_url, bound_key):
        # The selected broadcast's binding is authoritative; a stale env/CLI
        # key otherwise sends video elsewhere while chat appears to work.
        if not bound_url or not bound_key:
            raise ValueError("The selected YouTube broadcast has no usable RTMP ingest credentials")

        return bound_url, bound_key

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
            # Use the broadcast already selected through OAuth.
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
                logger.debug("Live chat for broadcast %s is not available yet", live_id)
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
        word_count = random.randint(60, 70)
        language_name = LANGUAGE_MAP.get(self.stream_language, "English")
        self._segment_counter += 1

        covered_list = list(self.covered_topics)
        covered_block = (
            "Previously covered themes & sub-points (DO NOT repeat any of these concepts, words, idioms, or scenarios):\n- "
            + "\n- ".join(covered_list[-80:])
            if covered_list
            else "No topics covered yet in this session."
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
            f"Target length for 'segment': ~{word_count} words (3–5 natural sentences in {language_name}; aim for about 30 seconds of speech).\n"
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
                max_tokens=450,
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
        """Queue synthesized audio; its acknowledgement is not playback completion."""
        logger.debug("Sending segment and waiting for response from AvatarTalk API...")
        audio_info = await self.avatartalk_connector.send_and_receive(segment)
        duration = float(audio_info.get("audio_duration", 0.0))
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError("AvatarTalk returned no usable audio duration")
        self.last_segment_sent_at = time.time()

        # The server has queued audio; video rendering/RTMP delivery may still be pending.
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
                        logger.info("Waiting for YouTube live chat; retrying in %s seconds", IDLE_WAIT_SECONDS)
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

        pacer = NarrationPacer()
        last_narrated_message_ts: datetime | None = None

        while not self.shutdown_requested:
            wait_for = pacer.generation_wait(time.monotonic())
            if wait_for > 0:
                wait_for = min(1.0, wait_for)
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

                # Keep one bounded lookahead, enough to fill the next 4.8 s
                # inference window before YouTube consumes the previous segment.
                while not self.shutdown_requested:
                    wait_for = pacer.send_wait(time.monotonic())
                    if wait_for <= 0:
                        break
                    if await self._sleep_or_shutdown(min(0.5, wait_for)):
                        break
                if self.shutdown_requested:
                    break

                duration = await self._play_segment(segment)
                new_connection = (
                    self.avatartalk_connector.first_chunk_on_ws or self.avatartalk_connector.reconnected_event
                )
                pacer.acknowledge(duration, time.monotonic(), new_connection=new_connection)
                self.avatartalk_connector.first_chunk_on_ws = False
                self.avatartalk_connector.reconnected_event = False
                logger.info("Estimated queued playback: %.1fs", max(0.0, pacer.playback_ends_at - time.monotonic()))

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
        check_interval = 15  # Poll less frequently after YouTube confirms live.
        restart_cooldown = 60  # Wait 60 seconds after restart before checking again

        _iteration = 0
        while not self.shutdown_requested:
            try:
                # Wait for the check interval
                if await self._sleep_or_shutdown(check_interval):
                    break


                # A renderer acknowledgement does not prove YouTube receives
                # video. Poll even while narration is active (also drives go-live).
                # Check stream status (run in dedicated executor to avoid blocking)
                try:
                    status = await asyncio.wait_for(
                        loop.run_in_executor(self._yt_executor, self.youtube_manager.get_stream_status, self.youtube_live_id),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.warning("Healthcheck: get_stream_status() timed out after 10s")
                    continue

                lifecycle = self.youtube_manager.broadcast_status
                if lifecycle == "live":
                    check_interval = 45
                elif lifecycle in ("liveStarting", "testStarting"):
                    logger.info("YouTube broadcast %s is starting (state=%s, ingest=%s)", self.youtube_live_id, lifecycle, status)
                elif lifecycle is not None:
                    logger.warning("YouTube broadcast %s is not live yet (state=%s, ingest=%s)", self.youtube_live_id, lifecycle, status)

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
                    if _iteration >= 6 and time.time() - self.last_connector_restart >= restart_cooldown:
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
                logger.info("Chat handling: %s", "READY" if self.youtube_manager.live_chat_id else "WAITING for YouTube chat")
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
