import asyncio
import contextlib
import logging
import os
import random
import signal
import sys
import time
from typing import Any

from openai import OpenAI

from livestream.avatartalk import AvatarTalkConnector
from livestream.config import (
    AVATARTALK_API_KEY,
    AVATARTALK_AVATAR,
    AVATARTALK_LANGUAGE,
    AVATARTALK_MODEL,
    AVATARTALK_TOPICS_FILE,
    AVATARTALK_URL,
    YOUTUBE_API_KEY,
    YOUTUBE_RTMP_URL,
    YOUTUBE_STREAM_KEY,
)
from livestream.youtube import YouTubeCommentManager

logger = logging.getLogger(__name__)


class AvatarTalkTeacher:
    """
    Coordinates topic selection, text generation, and streaming.

    This class fetches YouTube Live comments, generates short speaking
    segments using the OpenAI API, and streams them via AvatarTalk.
    """

    def __init__(self, live_id: str):
        self.client = self._init_openai_client()
        self.model = AVATARTALK_MODEL
        self.topics_file = AVATARTALK_TOPICS_FILE
        self.shutdown_requested = False
        self.room_name = "avatartalk-live"
        self.youtube_live_id = live_id
        # Cooldown to avoid overlapping segments while previous audio plays
        self.remaining_duration_to_play = 10

        # Rolling context - keep last 2 assistant messages
        self.context_history: list[dict] = []

        # Load topics
        self.topics = self._load_topics()
        self.avatartalk_connector = AvatarTalkConnector(
            AVATARTALK_URL,
            AVATARTALK_API_KEY,
            AVATARTALK_AVATAR,
            AVATARTALK_LANGUAGE,
            YOUTUBE_RTMP_URL,
            YOUTUBE_STREAM_KEY,
        )

        # System prompt
        self.system_prompt = """You are "AvatarTalk Teacher", a friendly English coach streaming live 24/7.
Your job is to produce short, engaging monologue segments about learning and using English.
Rules:
- Keep each segment ~60–90 English words (20–40 seconds when spoken).
- Use clear B1–B2 vocabulary.
- Structure: hook (1 sentence) → tip (1–2 sentences) → concrete example (1–2 sentences) → tiny task for the viewer (1 sentence) → end with a brief question inviting chat replies.
- Focus on practical topics: pronunciation, connected speech, phrasal verbs, politeness, travel scenarios, café/small talk, creators & small business use-cases.
- Avoid controversy and sensitive topics.
- Do not greet or introduce yourself every time; continue naturally.
- Never ask the user to type commands; just speak the content.
Return plain text only, no markdown."""

        # Set up YouTube comment manager
        youtube_api_key = YOUTUBE_API_KEY
        if youtube_api_key:
            self.youtube_manager = YouTubeCommentManager(youtube_api_key)
            self._setup_youtube_stream()
        else:
            logger.critical("YOUTUBE_API_KEY not provided")
            sys.exit(1)

        self.recent_comments: list[dict[str, Any]] = []
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
        """Build message list with system prompt, context history, and current user prompt."""
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add last 2 assistant messages for context
        messages.extend(self.context_history[-2:])

        # Add current user prompt
        messages.append({"role": "user", "content": user_prompt})

        return messages

    def _generate_segment(self, topic: str) -> str | None:
        """Generate a single monologue segment for the given topic."""
        user_prompt = self._create_user_prompt(topic)
        messages = self._build_messages(user_prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=200, temperature=0.8
            )

            segment = response.choices[0].message.content.strip()

            # Update rolling context with the new assistant message
            self.context_history.append({"role": "assistant", "content": segment})

            return segment

        except Exception as e:
            logger.exception("OpenAI API error: %s", e)
            return None

    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        logger.info("Stopping AvatarTalk Teacher...")
        self.shutdown_requested = True

    def _select_topic(self, comments: list[dict[str, Any]] | None) -> str:
        """Choose a topic from comments or randomly from the topics file."""
        if comments:
            logger.info("Retrieved %d new comments", len(comments))
            try:
                summary = self.youtube_manager.summarize_comments(comments)
                if summary:
                    return summary
            except Exception:
                logger.warning("Falling back to random topic after summarize failure")
        topic = random.choice(self.topics)
        logger.info("No new comments, using topic: %s", topic)
        return topic

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

    async def run_async(self) -> None:
        """Async main loop for handling RTMP and other async operations."""
        try:
            await self.avatartalk_connector.initialize()

            signal.signal(signal.SIGINT, self._handle_interrupt)

            logger.info("AvatarTalk Teacher starting with model: %s", self.model)
            logger.info("Press Ctrl+C to stop")
            if self.youtube_manager:
                logger.info("YouTube comment integration: ENABLED")

            cooldown_remaining = 0.0
            while not self.shutdown_requested:
                if cooldown_remaining >= self.remaining_duration_to_play:
                    await asyncio.sleep(1)
                    cooldown_remaining -= 1
                    continue

                try:
                    start_comment_processing = time.time()
                    comments = self.youtube_manager.get_recent_comments()

                    topic = self._select_topic(comments)

                    # Generate segment
                    segment = self._generate_segment(topic)
                    text_gen_duration = time.time() - start_comment_processing

                    if not segment:
                        # API error occurred, wait a bit longer before retrying
                        logger.warning("Segment generation failed; retrying soon...")
                        await asyncio.sleep(3.0)
                        continue

                    start_video_request = time.time()
                    duration = await self._play_segment(segment)

                    delay = duration - text_gen_duration - (time.time() - start_video_request)
                    cooldown_remaining += delay

                except KeyboardInterrupt:
                    logger.info("AvatarTalk Teacher stopped. Thanks for listening!")
                    break
                except Exception as e:
                    logger.exception("Unexpected error: %s", e)
                    break
        except Exception as e:
            logger.exception("Unexpected error during run: %s", e)
        finally:
            with contextlib.suppress(Exception):
                await self.avatartalk_connector.close()

    def run(self) -> None:
        """Main entry point - handles both sync and async components."""
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(self.run_async())
