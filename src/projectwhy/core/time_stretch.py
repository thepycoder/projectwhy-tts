"""Pitch-preserving tempo change via Rubber Band (pyrubberband + CLI)."""

from __future__ import annotations

import numpy as np
import pyrubberband as pyrb


def time_stretch(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Return audio played at *speed*× tempo with pitch preserved.

    *speed* > 1 shortens duration (faster). *speed* == 1 returns a float32 copy.

    Uses the Rubber Band library (R3 / ``--fine`` engine) for time stretch; requires
    the ``rubberband`` executable on ``PATH`` (e.g. distro package ``rubberband-cli``).
    """
    y = np.asarray(audio, dtype=np.float32).reshape(-1)
    if y.size == 0:
        return y
    if abs(float(speed) - 1.0) < 1e-6:
        return y.astype(np.float32, copy=False)
    sr = int(sample_rate)
    if sr <= 0:
        raise ValueError("sample_rate must be positive for time stretch")
    return np.asarray(
        pyrb.time_stretch(
            y,
            sr,
            float(speed),
            rbargs={"--fine": ""},
        ),
        dtype=np.float32,
    ).reshape(-1)
