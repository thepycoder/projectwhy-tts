"""Playback and filter controls."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class ControlBar(QWidget):
    play_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    prev_page_clicked = pyqtSignal()
    next_page_clicked = pyqtSignal()
    voice_changed = pyqtSignal(str)
    speed_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)

        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_stop = QPushButton("Stop")
        self.btn_prev = QPushButton("Prev page")
        self.btn_next = QPushButton("Next page")
        self.page_label = QLabel("Page 0 / 0")
        self.voice = QComboBox()
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(50, 200)
        self.speed.setValue(100)
        self.speed_label = QLabel("Speed 1.00x")

        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_stop)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_next)
        lay.addWidget(self.page_label)
        lay.addWidget(QLabel("Voice"))
        lay.addWidget(self.voice, stretch=1)
        lay.addWidget(self.speed_label)
        lay.addWidget(self.speed, stretch=1)

        self.btn_play.clicked.connect(self.play_clicked.emit)
        self.btn_pause.clicked.connect(self.pause_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_prev.clicked.connect(self.prev_page_clicked.emit)
        self.btn_next.clicked.connect(self.next_page_clicked.emit)
        self.voice.currentTextChanged.connect(self.voice_changed.emit)
        self.speed.valueChanged.connect(self._on_speed)

    def _on_speed(self, v: int) -> None:
        s = v / 100.0
        self.speed_label.setText(f"Speed {s:.2f}x")
        self.speed_changed.emit(s)

    def set_voices(self, names: list[str], current: str | None = None) -> None:
        self.voice.blockSignals(True)
        self.voice.clear()
        self.voice.addItems(names)
        if current and current in names:
            self.voice.setCurrentText(current)
        self.voice.blockSignals(False)

    def set_page_indicator(self, idx: int, total: int) -> None:
        self.page_label.setText(f"Page {idx + 1} / {total}")
