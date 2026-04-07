"""Discrete playback tempo options (multiplier, pitch-preserving stretch in session)."""

from __future__ import annotations

PLAYBACK_SPEED_CHOICES: tuple[float, ...] = (
    0.5,
    0.75,
    1.0,
    1.25,
    1.5,
    1.75,
    2.0,
)


def clamp_playback_speed(s: float) -> float:
    """Map any *s* to the nearest allowed speed."""
    x = float(s)
    return min(PLAYBACK_SPEED_CHOICES, key=lambda c: abs(c - x))
