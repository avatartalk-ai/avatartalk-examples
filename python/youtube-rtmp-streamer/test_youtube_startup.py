"""Offline regression tests; never authenticate or publish a YouTube stream."""

import ast
import asyncio
import contextlib
import logging
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).parent


def extract(filename, class_name, names):
    tree = ast.parse((ROOT / filename).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    cls.body = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    scope = dict(asyncio=asyncio, contextlib=contextlib, time=time, datetime=datetime, UTC=UTC,
                 logger=logging.getLogger(__name__), HttpError=RuntimeError)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), filename, "exec"), scope)
    return scope[class_name]


Manager = extract("livestream/youtube.py", "YouTubeCommentManager", {
    "find_live_stream", "_ensure_rtmp_stream", "_resolve_broadcast_stream", "ensure_live_broadcast", "get_stream_status", "get_live_chat_id",
})
Streamer = extract("livestream/core.py", "AvatarTalkStreamer", {"_select_ingestion", "_healthcheck_loop"})


def response(resource, method, data):
    getattr(resource, method).return_value.execute.return_value = data


class StartupTests(unittest.TestCase):
    def manager(self):
        manager = Manager()
        manager.youtube = Mock()
        manager._api_lock = threading.RLock()
        manager._ensure_valid_credentials = Mock()
        manager.broadcast_status = None
        manager.youtube.liveBroadcasts().list_next.return_value = None
        manager.youtube.liveStreams().list_next.return_value = None
        return manager

    def test_existing_broadcast_uses_its_bound_stream_not_first_language_match(self):
        m = self.manager()
        response(m.youtube.liveStreams(), "list", {"items": [{"id": "unrelated", "snippet": {"title": "English"}}]})
        response(m.youtube.liveBroadcasts(), "list", {"items": [{"status": {"lifeCycleStatus": "ready"},
                 "contentDetails": {"boundStreamId": "bound"}}]})
        response(m.youtube.liveStreams(), "list", {
            "items": [{"cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://bound", "streamName": "bound-key"}}}]})
        self.assertEqual(m.ensure_live_broadcast("video"), ("video", "rtmp://bound", "bound-key"))
        self.assertEqual(m.youtube.liveStreams().list.call_args.kwargs["id"], "bound")
        m.youtube.liveBroadcasts().bind.assert_not_called()

    def test_autodetected_created_broadcast_is_bound_before_streaming(self):
        m = self.manager()
        response(m.youtube.liveStreams(), "list", {"items": [{"id": "selected", "snippet": {"title": "English"},
                 "cdn": {"ingestionInfo": {"ingestionAddress": "rtmp://selected", "streamName": "key"}}}]})
        response(m.youtube.liveBroadcasts(), "list", {"items": [{"contentDetails": {}}]})
        m.find_live_stream = Mock(return_value="created-video")
        m._ensure_rtmp_stream = Mock(return_value="selected")
        self.assertEqual(m.ensure_live_broadcast(), ("created-video", "rtmp://selected", "key"))
        m.youtube.liveBroadcasts().bind.assert_called_once_with(
            id="created-video", part="id,contentDetails", streamId="selected")

    def test_missing_explicit_broadcast_does_not_create_another(self):
        m = self.manager()
        response(m.youtube.liveStreams(), "list", {"items": []})
        response(m.youtube.liveBroadcasts(), "list", {"items": []})
        with self.assertRaises(ValueError):
            m.ensure_live_broadcast("missing")
        m.youtube.liveBroadcasts().insert.assert_not_called()

    def test_ingestion_comes_only_from_oauth_binding(self):
        self.assertEqual(Streamer._select_ingestion("rtmp://bound", "bound-key"),
                         ("rtmp://bound", "bound-key"))
        with self.assertRaises(ValueError):
            Streamer._select_ingestion(None, None)

    def test_missing_rtmp_stream_is_created_automatically(self):
        m = self.manager()
        response(m.youtube.liveStreams(), "list", {"items": []})
        response(m.youtube.liveStreams(), "insert", {"id": "new-stream"})
        self.assertEqual(m._ensure_rtmp_stream("pl"), "new-stream")
        body = m.youtube.liveStreams().insert.call_args.kwargs["body"]
        self.assertEqual(body["cdn"], {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"})
        self.assertTrue(body["contentDetails"]["isReusable"])

    def test_existing_managed_rtmp_stream_is_reused(self):
        m = self.manager()
        response(m.youtube.liveStreams(), "list", {"items": [{
            "id": "managed", "snippet": {"title": "AvatarTalk en RTMP"}, "cdn": {"ingestionType": "rtmp"}}]})
        self.assertEqual(m._ensure_rtmp_stream("en"), "managed")
        m.youtube.liveStreams().insert.assert_not_called()

    def test_no_broadcast_creates_binds_and_resolves_automatically(self):
        m = self.manager()
        m.find_live_stream = Mock(return_value=None)
        m._ensure_rtmp_stream = Mock(return_value="new-stream")
        response(m.youtube.liveBroadcasts(), "insert", {"id": "new-video"})
        m._resolve_broadcast_stream = Mock(return_value=("new-video", "rtmp://auto", "auto-key"))
        self.assertEqual(m.ensure_live_broadcast(language="en"), ("new-video", "rtmp://auto", "auto-key"))
        m.youtube.liveBroadcasts().bind.assert_called_once_with(
            id="new-video", part="id,contentDetails", streamId="new-stream")
        m._resolve_broadcast_stream.assert_called_once_with("new-video", "new-stream")

    def test_language_detection_does_not_pick_other_language_on_shared_key(self):
        m = self.manager()
        response(m.youtube.liveBroadcasts(), "list", {"items": [
            {"id": "spanish", "snippet": {"title": "AI Spanish Coach"},
             "status": {"lifeCycleStatus": "live"}, "contentDetails": {"boundStreamId": "shared"}},
            {"id": "english", "snippet": {"title": "AI English Coach"},
             "status": {"lifeCycleStatus": "ready"}, "contentDetails": {"boundStreamId": "shared"}},
        ]})
        self.assertEqual(m.find_live_stream(language="en", stream_id="shared"), "english")

    def test_api_failure_does_not_create_duplicate_broadcast(self):
        m = self.manager()
        m.youtube.liveBroadcasts().list.return_value.execute.side_effect = RuntimeError("quota exhausted")
        with self.assertRaises(RuntimeError):
            m.ensure_live_broadcast()
        m.youtube.liveBroadcasts().insert.assert_not_called()

    def test_poll_refreshes_lifecycle_and_advances_testing_then_live(self):
        m = self.manager()
        broadcasts = m.youtube.liveBroadcasts()
        broadcasts.list.return_value.execute.side_effect = [
            {"items": [{"status": {"lifeCycleStatus": state}, "contentDetails": {
                "boundStreamId": "bound", "enableAutoStart": True,
                "monitorStream": {"enableMonitorStream": True}}}]} for state in ("ready", "testing", "live")
        ]
        response(m.youtube.liveStreams(), "list", {"items": [{"status": {"streamStatus": "active", "healthStatus": {"status": "good"}}}]})
        for _ in range(3):
            self.assertEqual(m.get_stream_status("video"), "active")
        self.assertEqual([c.kwargs["broadcastStatus"] for c in broadcasts.transition.call_args_list], ["testing", "live"])
        self.assertEqual(m.broadcast_status, "live")
        self.assertEqual(broadcasts.list.call_count, 3)

    def test_chat_id_resolves_from_owner_broadcast_before_video_is_live(self):
        m = self.manager()
        m.live_chat_id = None
        m.chat_start_ts = None
        response(m.youtube.liveBroadcasts(), "list", {"items": [{
            "snippet": {"liveChatId": "upcoming-chat"}, "status": {"lifeCycleStatus": "ready"}}]})
        self.assertEqual(m.get_live_chat_id("video"), "upcoming-chat")
        self.assertEqual(m.live_chat_id, "upcoming-chat")
        self.assertIsNotNone(m.chat_start_ts)
        m.youtube.videos.assert_not_called()

    def test_chat_not_published_yet_retries_without_error(self):
        m = self.manager()
        m.live_chat_id = None
        m.chat_start_ts = None
        m.youtube.liveBroadcasts().list.return_value.execute.side_effect = [
            {"items": [{"snippet": {}}]}, {"items": [{"snippet": {"liveChatId": "later-chat"}}]},
        ]
        with self.assertNoLogs(logging.getLogger(__name__), level="WARNING"):
            self.assertIsNone(m.get_live_chat_id("video"))
            self.assertEqual(m.get_live_chat_id("video"), "later-chat")

    def test_active_but_starved_ingest_is_not_reported_healthy(self):
        m = self.manager()
        response(m.youtube.liveBroadcasts(), "list", {"items": [{"status": {"lifeCycleStatus": "live"},
                 "contentDetails": {"boundStreamId": "bound"}}]})
        response(m.youtube.liveStreams(), "list", {"items": [{"status": {
            "streamStatus": "active", "healthStatus": {"status": "bad", "configurationIssues": [
                {"type": "videoIngestionStarved"}]}}}]})
        self.assertEqual(m.get_stream_status("video"), "bad")
        m.youtube.liveBroadcasts().transition.assert_not_called()

    def test_no_data_does_not_attempt_go_live(self):
        m = self.manager()
        response(m.youtube.liveBroadcasts(), "list", {"items": [{"status": {"lifeCycleStatus": "ready"},
                 "contentDetails": {"boundStreamId": "bound"}}]})
        response(m.youtube.liveStreams(), "list", {"items": [{"status": {"streamStatus": "ready", "healthStatus": {"status": "noData"}}}]})
        self.assertEqual(m.get_stream_status("video"), "noData")
        m.youtube.liveBroadcasts().transition.assert_not_called()

    def test_monitor_disabled_transitions_directly_to_live(self):
        m = self.manager()
        response(m.youtube.liveBroadcasts(), "list", {"items": [{"status": {"lifeCycleStatus": "ready"},
                 "contentDetails": {"boundStreamId": "bound", "monitorStream": {"enableMonitorStream": False}}}]})
        response(m.youtube.liveStreams(), "list", {"items": [{"status": {"streamStatus": "active"}}]})
        self.assertEqual(m.get_stream_status("video"), "active")
        self.assertEqual(m.youtube.liveBroadcasts().transition.call_args.kwargs["broadcastStatus"], "live")


class CliTests(unittest.TestCase):
    def test_no_arguments_ignore_stale_youtube_env_and_stream_key_file(self):
        import argparse
        import json
        import os
        from unittest.mock import patch

        tree = ast.parse((ROOT / "main.py").read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        scope = dict(argparse=argparse, json=json, os=os, logging=logging,
                     AVATARTALK_AVATAR="avatar", AVATARTALK_LANGUAGE="en", AvatarTalkStreamer=Mock())
        exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), "main.py", "exec"), scope)
        mapping = Mock(side_effect=lambda filename, lang: "avatar" if filename == "avatars.json" else None)
        scope["_load_optional_json_mapping"] = mapping
        with patch.dict(os.environ, {"YOUTUBE_LIVE_ID": "deleted-video", "YOUTUBE_STREAM_KEY": "stale-key"}):
            self.assertEqual(scope["main"]([]), 0)
        args = scope["AvatarTalkStreamer"].call_args.args
        self.assertIsNone(args[0])
        self.assertEqual(args[3], "avatar")
        self.assertNotIn("stream_keys.json", [call.args[0] for call in mapping.call_args_list])
        self.assertEqual(scope["parse_args"](["explicit-video"]).video_id, "explicit-video")


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_health_does_not_restart_active_publisher(self):
        s = Streamer()
        s.shutdown_requested = False
        s.last_connector_restart = 0
        s.youtube_live_id = "video"
        s.youtube_manager = Mock(broadcast_status="live")
        s.youtube_manager.get_stream_status.return_value = "bad"
        s.avatartalk_connector = Mock()
        waits = []

        async def sleep(seconds):
            waits.append(seconds)
            return len(waits) > 7

        s._sleep_or_shutdown = sleep
        with ThreadPoolExecutor(max_workers=1) as executor:
            s._yt_executor = executor
            await s._healthcheck_loop()
        self.assertEqual(s.youtube_manager.get_stream_status.call_count, 7)
        s.avatartalk_connector.restart.assert_not_called()

    async def test_recent_narration_does_not_skip_youtube_poll(self):
        s = Streamer()
        s.shutdown_requested = False
        s.last_connector_restart = s.last_segment_sent_at = time.time()
        s.youtube_live_id = "video"
        s.youtube_manager = Mock(broadcast_status="live")
        s.youtube_manager.get_stream_status.return_value = "active"
        sleeps = []

        async def sleep(seconds):
            sleeps.append(seconds)
            return len(sleeps) > 1

        s._sleep_or_shutdown = sleep
        with ThreadPoolExecutor(max_workers=1) as executor:
            s._yt_executor = executor
            await s._healthcheck_loop()
        s.youtube_manager.get_stream_status.assert_called_once_with("video")
        self.assertEqual(sleeps, [15, 45])


if __name__ == "__main__":
    unittest.main()
