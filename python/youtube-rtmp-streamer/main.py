"""CLI entrypoint for the AvatarTalk YouTube PoC."""

from __future__ import annotations

import argparse
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
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    video_id = args.video_id or YOUTUBE_LIVE_ID
    if not video_id:
        print(
            "Error: no video ID provided. Pass it as an argument or set $YOUTUBE_LIVE_ID.",
            file=sys.stderr,
        )
        return 2

    streamer = AvatarTalkStreamer(video_id, args.language, args.background_url)
    streamer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
