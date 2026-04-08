"""Modal settings window: sidebar categories + stacked pages."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig
from projectwhy.gui.settings.pages import (
    BlockTypesSettingsPage,
    GeneralSettingsPage,
    PdfTextSettingsPage,
    PlaybackSettingsPage,
)


class SettingsDialog(QDialog):
    """Host for category pages; add new pages by appending to *_build_pages."""

    def __init__(self, cfg: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(640, 420)
        self.resize(720, 480)
        self._cfg = cfg

        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body)

        self._nav = QListWidget()
        self._nav.setFixedWidth(180)
        self._nav.setSpacing(2)
        self._stack = QStackedWidget()

        body.addWidget(self._nav)
        body.addWidget(self._stack, stretch=1)

        self._pages: list = list(self._build_pages())
        for p in self._pages:
            item = QListWidgetItem(p.page_title())
            item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._nav.addItem(item)
            self._stack.addWidget(p.widget())

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_all()

    def _build_pages(self):
        """Register new settings sections here (order = sidebar order)."""
        return [
            PlaybackSettingsPage(),
            BlockTypesSettingsPage(),
            PdfTextSettingsPage(),
            GeneralSettingsPage(),
        ]

    def _load_all(self) -> None:
        for p in self._pages:
            p.load_from_config(self._cfg)

    def _on_accept(self) -> None:
        for p in self._pages:
            err = p.apply_to_config(self._cfg)
            if err:
                QMessageBox.warning(self, "Settings", err)
                self._load_all()
                return
        self.accept()
