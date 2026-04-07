"""Placeholder for future settings categories."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from projectwhy.config import AppConfig


class GeneralSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        lay = QVBoxLayout(self._root)
        lay.setContentsMargins(8, 8, 8, 8)
        msg = QLabel(
            "Additional options will appear here as the app grows "
            "(display, shortcuts, document defaults, etc.)."
        )
        msg.setWordWrap(True)
        lay.addWidget(msg)
        lay.addStretch(1)

    def page_title(self) -> str:
        return "General"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        pass

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        return None
