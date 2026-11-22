"""Bounded narration lookahead, independent of TTS acknowledgement latency."""

import math
from dataclasses import dataclass


@dataclass
class NarrationPacer:
    # Cover the 4.8 s renderer window plus synthesis/render/network jitter.
    generation_lead: float = 15.0
    send_lead: float = 10.0
    startup_offset: float = 3.5
    playback_ends_at: float = 0.0

    def generation_wait(self, now: float) -> float:
        return max(0.0, self.playback_ends_at - now - self.generation_lead)

    def send_wait(self, now: float) -> float:
        return max(0.0, self.playback_ends_at - now - self.send_lead)

    def acknowledge(self, duration: float, acknowledged_at: float, *, new_connection: bool) -> None:
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("AvatarTalk did not acknowledge a positive finite audio duration")
        if new_connection or self.playback_ends_at <= acknowledged_at:
            self.playback_ends_at = acknowledged_at + self.startup_offset + duration
        else:
            # TTS runs while the previous audio plays. Adding its response time
            # again on every segment would accumulate drift and starve RTMP.
            self.playback_ends_at += duration
