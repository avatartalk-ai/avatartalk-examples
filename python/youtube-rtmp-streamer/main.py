"""CLI entrypoint for the AvatarTalk YouTube PoC."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from livestream.config import AVATARTALK_AVATAR, AVATARTALK_LANGUAGE, YOUTUBE_LIVE_ID, YOUTUBE_STREAM_KEY
from livestream.core import AvatarTalkStreamer


def _load_optional_json_mapping(filename: str, key: str) -> str | None:
    """Load a language-keyed value from an optional JSON file if it exists."""
    if not os.path.exists(filename):
        return None
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AvatarTalk Teacher against a YouTube Live stream")
    parser.add_argument(
        "video_id",
        nargs="?",
        default=None,
        help="YouTube Live video ID. Falls back to $YOUTUBE_LIVE_ID if omitted.",
    )
    parser.add_argument("--background-url", type=str, default=None, help="Background image URL")
    parser.add_argument(
        "--language",
        type=str,
        default=AVATARTALK_LANGUAGE or "en",
        help="Language to use in stream (default: $AVATARTALK_LANGUAGE or 'en')",
    )
    parser.add_argument("--stream-key", type=str, default=None, help="YouTube RTMP stream key (overrides env/json)")
    parser.add_argument("--avatar", type=str, default=None, help="AvatarTalk avatar name (overrides env/json)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--skip-welcome",
        action="store_true",
        help="Skip initial welcome/greeting segments (useful when restarting stream)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting AvatarTalk YouTube Streamer")
    logger.info("Log level: %s", args.log_level)
    logger.info("Language: %s", args.language)

    video_id = args.video_id or YOUTUBE_LIVE_ID
    if not video_id:
        logger.info("No video ID passed via CLI/env — will auto-detect or create a broadcast via YouTube OAuth.")

    try:
        voice_id = _load_optional_json_mapping("voices.json", args.language) or "default"
        logger.debug("Voice ID: %s", voice_id)

        stream_key = (
            args.stream_key
            or _load_optional_json_mapping("stream_keys.json", args.language)
            or YOUTUBE_STREAM_KEY
            or ""
        )

        avatar_name = (
            args.avatar
            or _load_optional_json_mapping("avatars.json", args.language)
            or AVATARTALK_AVATAR
            or "european_man"
        )
        logger.debug("Avatar name: %s", avatar_name)

        logger.info("Initializing AvatarTalkStreamer")
        if args.skip_welcome:
            logger.info("Skip welcome mode: ENABLED (will delay initial narration)")
        streamer = AvatarTalkStreamer(
            video_id, args.language, voice_id, stream_key, avatar_name, args.background_url,
            skip_welcome=args.skip_welcome
        )

        logger.info("Starting streamer")
        streamer.run()

        logger.info("Streamer exited normally")
        return 0

    except FileNotFoundError as e:
        logger.critical("Required configuration file not found: %s", e.filename)
        logger.exception("Full error details:")
        return 1
    except json.JSONDecodeError as e:
        logger.critical("Invalid JSON in configuration file: %s", e)
        logger.exception("Full error details:")
        return 1
    except ValueError as e:
        logger.critical("Configuration error: %s", e)
        logger.exception("Full error details:")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        logger.critical("Unexpected error in main(): %s", e)
        logger.exception("Full traceback:")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
