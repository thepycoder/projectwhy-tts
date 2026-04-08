"""AudioPlayer: stale finished_callback must not fire the next play's on_complete."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def test_abort_does_not_invoke_next_on_complete() -> None:
    from projectwhy.core.player import AudioPlayer

    audio = np.zeros(48000, dtype=np.float32)
    calls: list[str] = []
    finished_callbacks: list = []

    def make_stream(**kwargs):
        finished_callbacks.append(kwargs.get("finished_callback"))
        stream = MagicMock()
        stream.start = MagicMock()
        stream.abort = MagicMock()
        stream.close = MagicMock()
        return stream

    with patch("projectwhy.core.player.sd.OutputStream", side_effect=make_stream):
        p = AudioPlayer()
        p.play(audio, 24000, on_complete=lambda: calls.append("first"))
        p.play(audio, 24000, on_complete=lambda: calls.append("second"))

        assert len(finished_callbacks) == 2
        finished_callbacks[0]()

    assert calls == [], "stale finished must not run either callback"

    finished_callbacks[1]()
    assert calls == ["second"]


def test_play_start_sec_sets_initial_frame() -> None:
    from projectwhy.core.player import AudioPlayer

    audio = np.zeros(48_000, dtype=np.float32)
    stream = MagicMock()
    stream.start = MagicMock()
    stream.abort = MagicMock()
    stream.close = MagicMock()

    with patch("projectwhy.core.player.sd.OutputStream", return_value=stream):
        p = AudioPlayer()
        p.play(audio, 24_000, start_sec=0.5)

    assert p.get_position_sec() == pytest.approx(0.5)
