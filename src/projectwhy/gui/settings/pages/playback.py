"""Playback / pipeline settings."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig
from projectwhy.core.playback_speed import PLAYBACK_SPEED_CHOICES, clamp_playback_speed


class PlaybackSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Controls how many synthesized utterances are kept in the TTS cache, "
            "and how many blocks are pre-warmed ahead of the current position."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Pipeline")
        form = QFormLayout(group)

        self._cache_entries = QSpinBox()
        self._cache_entries.setRange(4, 500)
        self._cache_entries.setToolTip(
            "Maximum number of synthesized blocks held in the TTS audio cache. "
            "Larger values let you navigate back instantly over more history; uses more RAM."
        )
        form.addRow("TTS cache entries:", self._cache_entries)

        self._lookahead = QSpinBox()
        self._lookahead.setRange(1, 20)
        self._lookahead.setToolTip(
            "How many upcoming speakable blocks are pre-synthesized in the background "
            "(higher = smoother auto-play, more TTS work and RAM)."
        )
        form.addRow("Speakable lookahead:", self._lookahead)

        self._playback_speed = QComboBox()
        for sp in PLAYBACK_SPEED_CHOICES:
            self._playback_speed.addItem(f"{sp:.2f}x", sp)
        self._playback_speed.setToolTip(
            "Tempo multiplier for spoken audio (pitch preserved via WSOLA). "
            "Steps from 0.5x to 2x in 0.25 increments."
        )
        form.addRow("Playback speed:", self._playback_speed)

        outer.addWidget(group)
        outer.addStretch(1)

    def page_title(self) -> str:
        return "Playback"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        self._cache_entries.setValue(cfg.reading.tts_cache_max_entries)
        self._lookahead.setValue(cfg.reading.prefetch_lookahead)
        c = clamp_playback_speed(cfg.reading.playback_speed)
        self._playback_speed.setCurrentIndex(PLAYBACK_SPEED_CHOICES.index(c))

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        cfg.reading.tts_cache_max_entries = self._cache_entries.value()
        cfg.reading.prefetch_lookahead = self._lookahead.value()
        cfg.reading.playback_speed = float(self._playback_speed.currentData())
        return None
