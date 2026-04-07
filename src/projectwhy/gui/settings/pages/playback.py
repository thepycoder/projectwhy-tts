"""Playback / pipeline settings."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig


class PlaybackSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Controls how far you can skip backward with cached audio, and how many "
            "blocks are synthesized ahead of playback."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Pipeline")
        form = QFormLayout(group)

        self._history = QSpinBox()
        self._history.setRange(1, 500)
        self._history.setToolTip(
            "Maximum number of recently played blocks kept in memory for Prev block "
            "(reuses TTS audio without re-synthesis)."
        )
        form.addRow("Block history size:", self._history)

        self._lookahead = QSpinBox()
        self._lookahead.setRange(1, 20)
        self._lookahead.setToolTip(
            "How many upcoming speakable blocks may be waiting in the prefetch queue "
            "(higher = smoother skipping forward, more RAM and TTS work)."
        )
        form.addRow("Prefetch queue depth:", self._lookahead)

        self._playback_speed = QDoubleSpinBox()
        self._playback_speed.setRange(0.5, 3.0)
        self._playback_speed.setDecimals(2)
        self._playback_speed.setSingleStep(0.05)
        self._playback_speed.setToolTip(
            "Tempo multiplier for spoken audio with pitch preserved (Rubber Band). "
            "Requires the rubberband program on PATH when not 1.0."
        )
        form.addRow("Playback speed:", self._playback_speed)

        outer.addWidget(group)
        outer.addStretch(1)

    def page_title(self) -> str:
        return "Playback"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        self._history.setValue(cfg.reading.history_length)
        self._lookahead.setValue(cfg.reading.prefetch_lookahead)
        self._playback_speed.setValue(cfg.reading.playback_speed)

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        cfg.reading.history_length = self._history.value()
        cfg.reading.prefetch_lookahead = self._lookahead.value()
        cfg.reading.playback_speed = float(self._playback_speed.value())
        return None
