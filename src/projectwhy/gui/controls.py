"""Playback and filter controls."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from projectwhy.core.playback_speed import PLAYBACK_SPEED_CHOICES, clamp_playback_speed


class ControlBar(QWidget):
    play_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    prev_page_clicked = pyqtSignal()
    next_page_clicked = pyqtSignal()
    page_jump_requested = pyqtSignal(int)
    prev_block_clicked = pyqtSignal()
    next_block_clicked = pyqtSignal()
    voice_changed = pyqtSignal(str)
    speed_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)

        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_prev = QPushButton("Prev page")
        self.btn_next = QPushButton("Next page")
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("page")
        self.page_edit.setFixedWidth(52)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._page_index = 0
        self._page_total = 0
        self.page_total_label = QLabel("of 0")
        self.btn_prev_block = QPushButton("Prev block")
        self.btn_next_block = QPushButton("Next block")
        self.voice = QComboBox()
        self.speed = QComboBox()
        for sp in PLAYBACK_SPEED_CHOICES:
            self.speed.addItem(f"{sp:.2f}x", sp)
        self.speed.setCurrentIndex(PLAYBACK_SPEED_CHOICES.index(1.0))

        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_next)
        lay.addWidget(QLabel("Page"))
        lay.addWidget(self.page_edit)
        lay.addWidget(self.page_total_label)
        lay.addWidget(self.btn_prev_block)
        lay.addWidget(self.btn_next_block)
        lay.addWidget(QLabel("Voice"))
        lay.addWidget(self.voice, stretch=1)
        lay.addWidget(QLabel("Speed"))
        lay.addWidget(self.speed)

        self.btn_play.clicked.connect(self.play_clicked.emit)
        self.btn_pause.clicked.connect(self.pause_clicked.emit)
        self.btn_prev.clicked.connect(self.prev_page_clicked.emit)
        self.btn_next.clicked.connect(self.next_page_clicked.emit)
        self.page_edit.returnPressed.connect(self._on_page_edit_return)
        self.page_edit.installEventFilter(self)
        self.btn_prev_block.clicked.connect(self.prev_block_clicked.emit)
        self.btn_next_block.clicked.connect(self.next_block_clicked.emit)
        self.voice.currentIndexChanged.connect(self._emit_voice_changed)
        self.speed.currentIndexChanged.connect(self._on_speed_index)

    def _emit_voice_changed(self, _idx: int | None = None) -> None:
        data = self.voice.currentData()
        if data is not None:
            self.voice_changed.emit(str(data))
        else:
            self.voice_changed.emit(self.voice.currentText())

    def _on_speed_index(self, _idx: int) -> None:
        s = float(self.speed.currentData())
        self.speed_changed.emit(s)

    def set_playback_speed(self, s: float) -> None:
        c = clamp_playback_speed(s)
        idx = PLAYBACK_SPEED_CHOICES.index(c)
        self.speed.blockSignals(True)
        self.speed.setCurrentIndex(idx)
        self.speed.blockSignals(False)

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if obj is self.page_edit and event is not None and event.type() == QEvent.Type.FocusOut:
            if self._page_total > 0:
                self.page_edit.setText(str(self._page_index + 1))
        return super().eventFilter(obj, event)

    def _on_page_edit_return(self) -> None:
        if self._page_total <= 0:
            return
        text = self.page_edit.text().strip()
        if not text:
            self.page_edit.setText(str(self._page_index + 1))
            return
        try:
            n = int(text, 10)
        except ValueError:
            self.page_edit.setText(str(self._page_index + 1))
            return
        if n < 1 or n > self._page_total:
            self.page_edit.setText(str(self._page_index + 1))
            return
        self.page_jump_requested.emit(n - 1)

    def set_voices(
        self,
        names: list[str],
        current: str | None = None,
        *,
        voice_values: list[str] | None = None,
    ) -> None:
        self.voice.blockSignals(True)
        self.voice.clear()
        if voice_values is not None and len(voice_values) == len(names):
            for label, value in zip(names, voice_values):
                self.voice.addItem(label, value)
            if current:
                idx = self.voice.findData(current)
                if idx >= 0:
                    self.voice.setCurrentIndex(idx)
        else:
            self.voice.addItems(names)
            if current and current in names:
                self.voice.setCurrentText(current)
        self.voice.blockSignals(False)

    def set_page_indicator(self, idx: int, total: int) -> None:
        self._page_index = idx
        self._page_total = total
        self.page_edit.setEnabled(total > 0)
        self.page_total_label.setText(f"of {total}" if total > 0 else "of 0")
        if not self.page_edit.hasFocus():
            if total > 0:
                self.page_edit.setText(str(idx + 1))
            else:
                self.page_edit.clear()
