"""Deterministic scheduling checks; no API calls or live publishing."""

import asyncio
import math
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from livestream.pacing import NarrationPacer
from test_youtube_startup import extract


class PacingTests(unittest.TestCase):
    def test_prompt_targets_thirty_seconds_with_sixty_to_seventy_words(self):
        cls = extract("livestream/core.py", "AvatarTalkStreamer", {"_create_user_prompt"})
        random = Mock()
        random.randint.return_value = 65
        cls._create_user_prompt.__globals__.update(
            random=random, LANGUAGE_MAP={"en": "English"},
            THEME_DOMAINS=["work"], ARC_STEPS=["introduce", "explain", "practice", "recap"],
        )
        streamer = cls()
        streamer.stream_language = "en"
        streamer._segment_counter = streamer._arc_step = streamer._theme_index = 0
        streamer.current_theme = None
        streamer.covered_topics = []
        prompt = streamer._create_user_prompt()
        random.randint.assert_called_once_with(60, 70)
        self.assertIn("~65 words", prompt)
        self.assertIn("about 30 seconds", prompt)

    def test_narration_prompts_never_insert_website_promotions(self):
        cls = extract("livestream/core.py", "AvatarTalkStreamer", {"_create_user_prompt"})
        cls._create_user_prompt.__globals__.update(
            random=SimpleNamespace(randint=lambda *_: 65), LANGUAGE_MAP={"en": "English"},
            THEME_DOMAINS=["work"], ARC_STEPS=["introduce", "explain", "practice", "recap"],
        )
        streamer = cls()
        streamer.stream_language = "en"
        streamer._segment_counter = streamer._arc_step = streamer._theme_index = 0
        streamer.current_theme = None
        streamer.covered_topics = []
        for _ in range(160):
            prompt = streamer._create_user_prompt()
            assert "avatartalk" not in prompt.lower()  # noqa: S101 - regression assertion
            assert "optional mention" not in prompt  # noqa: S101 - regression assertion
        assert streamer._segment_counter == 160  # noqa: S101 - preserve logging counter

    def test_ack_latency_is_not_added_to_existing_playback(self):
        pacer = NarrationPacer()
        pacer.acknowledge(30, 2, new_connection=True)
        self.assertEqual(pacer.playback_ends_at, 35.5)
        pacer.acknowledge(28, 27, new_connection=False)
        self.assertEqual(pacer.playback_ends_at, 63.5)
        self.assertEqual(pacer.send_wait(40), 13.5)

    def test_reconnect_discards_old_queued_playback(self):
        pacer = NarrationPacer(playback_ends_at=300)
        pacer.acknowledge(30, 50, new_connection=True)
        self.assertEqual(pacer.playback_ends_at, 83.5)

    def test_underrun_rebases_instead_of_sending_unbounded_catchup(self):
        pacer = NarrationPacer(playback_ends_at=10)
        pacer.acknowledge(30, 20, new_connection=False)
        self.assertEqual(pacer.playback_ends_at, 53.5)
        self.assertGreater(pacer.generation_wait(20), 0)

    def test_invalid_durations_do_not_change_clock(self):
        for value in (0, -1, math.nan, math.inf):
            pacer = NarrationPacer(playback_ends_at=100)
            with self.assertRaises(ValueError):
                pacer.acknowledge(value, 10, new_connection=False)
            self.assertEqual(pacer.playback_ends_at, 100)

    def test_long_run_lookahead_is_bounded_and_covers_inference_window(self):
        pacer = NarrationPacer()
        now = 0.0
        gaps = []
        previous_sent = None
        for index in range(100):
            now += pacer.generation_wait(now)
            now += 2  # OpenAI response
            now += pacer.send_wait(now)
            if previous_sent is not None:
                gaps.append(now - previous_sent)
                self.assertAlmostEqual(pacer.playback_ends_at - now, 10)
            previous_sent = now
            now += 2  # TTS acknowledgement while the previous segment plays
            pacer.acknowledge(30, now, new_connection=index == 0)
            self.assertLessEqual(pacer.playback_ends_at - now, 40)
        self.assertTrue(all(gap <= 30 for gap in gaps))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_narration_loop_sends_ahead_without_clock_drift(self):
        cls = extract("livestream/core.py", "AvatarTalkStreamer", {"_narration_loop"})
        now = [0.0]
        cls._narration_loop.__globals__.update(
            time=SimpleNamespace(monotonic=lambda: now[0]),
            NarrationPacer=NarrationPacer, partial=partial,
        )
        streamer = cls()
        streamer.skip_welcome = False
        streamer._welcome_skip_complete = True
        streamer.shutdown_requested = False
        streamer.context_store = SimpleNamespace(get_recent_chat_messages=lambda **kwargs: [])
        streamer.avatartalk_connector = SimpleNamespace(first_chunk_on_ws=True, reconnected_event=False)
        streamer._generate_segment = lambda hint: "generated speech"
        sent = []

        async def sleep(seconds):
            now[0] += seconds
            await asyncio.sleep(0)
            return False

        async def play(segment):
            sent.append(now[0])
            now[0] += 2
            if len(sent) == 4:
                streamer.shutdown_requested = True
            return 30

        streamer._sleep_or_shutdown = sleep
        streamer._play_segment = play
        await asyncio.wait_for(streamer._narration_loop(), 2)
        self.assertEqual(sent, [0, 25.5, 55.5, 85.5])

    async def test_actual_play_segment_rejects_failed_synthesis(self):
        cls = extract("livestream/core.py", "AvatarTalkStreamer", {"_play_segment"})
        cls._play_segment.__globals__["math"] = math
        streamer = cls()
        streamer.avatartalk_connector = SimpleNamespace(send_and_receive=AsyncMock(return_value={"audio_duration": 0}))
        with self.assertRaises(RuntimeError):
            await streamer._play_segment("text")


if __name__ == "__main__":
    unittest.main()
