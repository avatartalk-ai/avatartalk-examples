"""CLI entrypoint for the AvatarTalk YouTube PoC."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from livestream.config import YOUTUBE_LIVE_ID
from livestream.core import AvatarTalkStreamer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AvatarTalk Teacher against a YouTube Live stream")
    parser.add_argument(
        "video_id",
        nargs="?",
        default=None,
        help="YouTube Live video ID. Falls back to $YOUTUBE_LIVE_ID if omitted.",
    )
    parser.add_argument("--background-url", type=str, default=None, help="Background image URL")
    parser.add_argument("--language", type=str, default="en", help="Language to use in stream")
    parser.add_argument("--stream-key", type=str, help="Stream key to use")
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
        logger.critical("No video ID provided. Pass it as an argument or set $YOUTUBE_LIVE_ID.")
        print(
            "Error: no video ID provided. Pass it as an argument or set $YOUTUBE_LIVE_ID.",
            file=sys.stderr,
        )
        return 2

    try:
        # load voice ID
        logger.debug("Loading voices.json")
        with open("voices.json") as f:
            voices = json.load(f)

        if args.language not in voices:
            logger.critical("No voice ID for language '%s' in voices.json", args.language)
            raise ValueError(f"No voice ID for `{args.language}` language")

        voice_id = voices[args.language]
        logger.debug("Voice ID: %s", voice_id)

        # load stream key
        logger.debug("Loading stream_keys.json")
        with open("stream_keys.json") as f:
            stream_keys = json.load(f)

        if args.language not in stream_keys:
            logger.critical("No stream key for language '%s' in stream_keys.json", args.language)
            raise ValueError(f"No stream key for `{args.language}` language")

        stream_key = stream_keys[args.language]
        logger.debug("Stream key loaded successfully")

        # load avatar name
        logger.debug("Loading avatars.json")
        with open("avatars.json") as f:
            avatars = json.load(f)

        if args.language not in avatars:
            logger.critical("No avatar name for language '%s' in avatars.json", args.language)
            raise ValueError(f"No avatar name for `{args.language}` language")

        avatar_name = avatars[args.language]
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
