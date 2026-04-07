"""Pitch-preserving tempo change via Rubber Band (requires ``rubberband`` CLI on PATH)."""

from __future__ import annotations

import numpy as np
import pyrubberband as pyrb


def time_stretch(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Return audio played at *speed*× tempo with pitch preserved.

    *speed* > 1 shortens duration (faster). *speed* == 1 returns a float32 copy.
    """
    y = np.asarray(audio, dtype=np.float32).reshape(-1)
    if y.size == 0:
        return y
    if abs(float(speed) - 1.0) < 1e-6:
        return y.astype(np.float32, copy=False)
    out = pyrb.time_stretch(y, sample_rate, float(speed))
    return np.asarray(out, dtype=np.float32).reshape(-1)
