"""Inspector dock: block table, text detail, overlay toggle."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QShowEvent, QHideEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QHeaderView,
    QLabel,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from projectwhy.core.models import Page, ReadingState
from projectwhy.core.prefetch import BlockJob, JobStatus
from projectwhy.core.session import ReadingSession
from projectwhy.gui.inspector.colors import rgb_for_block_type


class LayoutPanel(QWidget):
    overlay_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self._overlay_cb = QCheckBox("Show block overlays")
        self._overlay_cb.setChecked(True)
        self._overlay_cb.toggled.connect(self.overlay_toggled.emit)
        lay.addWidget(self._overlay_cb)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "Type", "Text", "Action"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._table)

    def overlays_enabled(self) -> bool:
        return self._overlay_cb.isChecked()

    def update_page(self, page: Page, state: ReadingState) -> None:
        blocks = page.blocks
        self._table.setRowCount(len(blocks))
        active_idx = state.block_index

        base_flags = (
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
        )

        for i, block in enumerate(blocks):
            rgb = rgb_for_block_type(block.block_type)

            n_item = QTableWidgetItem(str(i))
            n_item.setFlags(base_flags)
            self._table.setItem(i, 0, n_item)

            t_item = QTableWidgetItem(block.block_type.value)
            t_item.setFlags(base_flags)
            t_item.setBackground(QColor(rgb[0], rgb[1], rgb[2], 60))
            self._table.setItem(i, 1, t_item)

            text = block.text
            text_prev = (text[:60] + "…") if len(text) > 60 else text
            x_item = QTableWidgetItem(text_prev)
            x_item.setFlags(base_flags)
            self._table.setItem(i, 2, x_item)

            action = "Speak" if ReadingSession._should_speak(block) else "Skip"
            a_item = QTableWidgetItem(action)
            a_item.setFlags(base_flags)
            self._table.setItem(i, 3, a_item)

            if i == active_idx:
                row_bg = QColor(255, 220, 100, 140) if state.is_playing else QColor(200, 230, 255, 100)
                for c in range(4):
                    it = self._table.item(i, c)
                    if it is not None:
                        it.setBackground(row_bg)


class DetailPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_page = -1
        self._last_block = -2
        lay = QVBoxLayout(self)
        self._header = QLabel()
        lay.addWidget(self._header)
        lay.addWidget(QLabel("Block text (TTS input)"))
        self._block_text = QTextEdit()
        self._block_text.setReadOnly(True)
        lay.addWidget(self._block_text)
        lay.addWidget(QLabel("Words (order, text, bbox)"))
        self._words = QTextEdit()
        self._words.setReadOnly(True)
        lay.addWidget(self._words)

    def reset_tracking(self) -> None:
        self._last_page = -1
        self._last_block = -2

    def update_page(self, page: Page, state: ReadingState) -> None:
        if state.page_index == self._last_page and state.block_index == self._last_block:
            return
        self._last_page = state.page_index
        self._last_block = state.block_index

        bi = state.block_index
        if bi < 0 or bi >= len(page.blocks):
            self._header.setText("No block selected")
            self._block_text.clear()
            self._words.clear()
            return

        block = page.blocks[bi]
        self._header.setText(f"Block #{bi} — {block.block_type.value}")
        self._block_text.setPlainText(block.text)

        lines: list[str] = []
        for wi, w in enumerate(block.words):
            bb = w.bbox
            lines.append(
                f"{wi}. {w.text!r}  "
                f"[{bb.x1:.1f},{bb.y1:.1f}–{bb.x2:.1f},{bb.y2:.1f}]",
            )
        self._words.setPlainText("\n".join(lines) if lines else "(no words)")


_STATUS_COLORS: dict[JobStatus, tuple[int, int, int, int]] = {
    JobStatus.SYNTHESIZING: (200, 220, 255, 140),
    JobStatus.READY: (180, 255, 180, 140),
    JobStatus.PLAYING: (255, 220, 100, 140),
    JobStatus.DONE: (220, 220, 220, 100),
}


class PipelinePanel(QWidget):
    """Shows the prefetch pipeline: which blocks are being synthesized / ready / playing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Page", "Block", "Type", "Status"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._table)

        self._empty_label = QLabel("Not playing")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._empty_label)

    def update_jobs(self, jobs: list[BlockJob]) -> None:
        has_jobs = bool(jobs)
        self._table.setVisible(has_jobs)
        self._empty_label.setVisible(not has_jobs)
        if not has_jobs:
            self._table.setRowCount(0)
            return

        base_flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        self._table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            page_item = QTableWidgetItem(str(job.page_index + 1))
            page_item.setFlags(base_flags)
            self._table.setItem(i, 0, page_item)

            block_item = QTableWidgetItem(str(job.block_index))
            block_item.setFlags(base_flags)
            self._table.setItem(i, 1, block_item)

            type_text = job.block.block_type.value if job.block else "—"
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(base_flags)
            self._table.setItem(i, 2, type_item)

            status_item = QTableWidgetItem(job.status.value)
            status_item.setFlags(base_flags)
            rgba = _STATUS_COLORS.get(job.status)
            if rgba:
                status_item.setBackground(QColor(*rgba))
            self._table.setItem(i, 3, status_item)


class InspectorDock(QDockWidget):
    overlay_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Inspector", parent)
        self.setObjectName("InspectorDock")

        tabs = QTabWidget()
        self._layout_panel = LayoutPanel()
        self._layout_panel.overlay_toggled.connect(self.overlay_toggled.emit)
        tabs.addTab(self._layout_panel, "Layout")
        self._detail = DetailPanel()
        tabs.addTab(self._detail, "Detail")
        self._pipeline = PipelinePanel()
        tabs.addTab(self._pipeline, "Pipeline")
        self.setWidget(tabs)

    def reset(self) -> None:
        self._detail.reset_tracking()

    def overlays_enabled(self) -> bool:
        return self._layout_panel.overlays_enabled()

    def update_page(self, page: Page, state: ReadingState) -> None:
        self._layout_panel.update_page(page, state)
        self._detail.update_page(page, state)

    def update_pipeline(self, jobs: list[BlockJob]) -> None:
        self._pipeline.update_jobs(jobs)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.overlay_toggled.emit(self._layout_panel.overlays_enabled())

    def hideEvent(self, event: QHideEvent) -> None:
        self.overlay_toggled.emit(False)
        super().hideEvent(event)
