"""PP-DocLayout block class: speak / pause-after."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig
from projectwhy.core.models import BlockType
from projectwhy.core.session import merged_block_config


class BlockTypesSettingsPage:
    def __init__(self) -> None:
        self._ordered = sorted(BlockType, key=lambda t: t.value)
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Each row is a PP-DocLayout class name. "
            "Speak controls TTS for blocks that have text; empty regions are never kept."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self._table = QTableWidget(len(self._ordered), 3)
        self._table.setHorizontalHeaderLabels(["Layout class", "Speak", "Pause after (s)"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for i, bt in enumerate(self._ordered):
            name = QTableWidgetItem(bt.value)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(i, 0, name)

            cb = QCheckBox()
            cb.setStyleSheet("margin-left: 8px;")
            self._table.setCellWidget(i, 1, cb)

            sp = QDoubleSpinBox()
            sp.setRange(0.0, 120.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.05)
            sp.setToolTip("Silence after this block finishes (seconds).")
            self._table.setCellWidget(i, 2, sp)

        outer.addWidget(self._table)

    def page_title(self) -> str:
        return "Block types"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        m = merged_block_config(cfg.blocks.types)
        for i, bt in enumerate(self._ordered):
            row = m[bt]
            cb = self._table.cellWidget(i, 1)
            sp = self._table.cellWidget(i, 2)
            assert isinstance(cb, QCheckBox) and isinstance(sp, QDoubleSpinBox)
            cb.setChecked(bool(row["speak"]))
            sp.setValue(float(row["pause_after"]))

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        types: dict[str, dict[str, Any]] = {}
        for i, bt in enumerate(self._ordered):
            cb = self._table.cellWidget(i, 1)
            sp = self._table.cellWidget(i, 2)
            if not isinstance(cb, QCheckBox) or not isinstance(sp, QDoubleSpinBox):
                continue
            types[bt.value] = {"speak": cb.isChecked(), "pause_after": float(sp.value())}
        cfg.blocks.types = types
        return None
