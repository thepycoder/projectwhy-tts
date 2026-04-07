"""Pitch-preserving tempo change via WSOLA (pytsmod), tuned for speech-like audio."""

from __future__ import annotations

import numpy as np
import pytsmod as tsm


def time_stretch(audio: np.ndarray, _sample_rate: int, speed: float) -> np.ndarray:
    """Return audio played at *speed*× tempo with pitch preserved.

    *speed* > 1 shortens duration (faster). *speed* == 1 returns a float32 copy.

    Uses waveform-similarity overlap-add (WSOLA) instead of a phase vocoder, which
    tends to avoid the smeared / “echoey” character phase methods add on TTS.
    *_sample_rate* is reserved for API compatibility with the session.
    """
    y = np.asarray(audio, dtype=np.float32).reshape(-1)
    if y.size == 0:
        return y
    if abs(float(speed) - 1.0) < 1e-6:
        return y.astype(np.float32, copy=False)
    # pytsmod: s > 1 lengthens (slower playback); our speed > 1 means faster → shorter.
    s = 1.0 / float(speed)
    y64 = y.astype(np.float64, copy=False).reshape(1, -1)
    out = tsm.wsola(y64, s=s)
    return np.asarray(out, dtype=np.float32).reshape(-1)
