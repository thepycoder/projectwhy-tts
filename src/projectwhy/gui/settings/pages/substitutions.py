"""Global and per-document TTS substitution rules: per-word find-and-replace, optional regex."""

from __future__ import annotations

import logging
from pathlib import Path

import tomli_w

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig, SubstitutionRuleConfig

logger = logging.getLogger(__name__)


def _load_sidecar_raw(doc_path: str) -> list[dict]:
    """Return raw rule dicts from sidecar, or [] if absent/unreadable."""
    try:
        import tomllib  # type: ignore[import]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    sidecar = Path(doc_path + ".projectwhy.toml")
    if not sidecar.exists():
        return []
    try:
        data = tomllib.loads(sidecar.read_text(encoding="utf-8"))
        raw = data.get("substitutions", {}).get("rules", [])
        return raw if isinstance(raw, list) else []
    except Exception:
        logger.exception("failed to read sidecar %s", sidecar)
        return []


def _write_sidecar(doc_path: str, rules: list[SubstitutionRuleConfig]) -> None:
    sidecar = Path(doc_path + ".projectwhy.toml")
    data: dict = {"substitutions": {"rules": [
        {"find": r.find, "replace": r.replace, "regex": r.regex} for r in rules
    ]}}
    with sidecar.open("wb") as f:
        tomli_w.dump(data, f)


class SubstitutionsSettingsPage:
    def __init__(self, doc_path: str | None = None) -> None:
        self._doc_path = doc_path
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        if doc_path:
            doc_name = Path(doc_path).name
            intro_text = (
                f"Rules are applied in order to each word before synthesis. "
                f"Check \"This doc\" to restrict a rule to the current document ({doc_name})."
            )
        else:
            intro_text = (
                "Rules are applied in order to each word before synthesis. "
                "Open a document to be able to add document-specific rules."
            )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Find", "Replace", "Regex", "This doc"])
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add rule")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    def _add_row(self, *, find: str = "", replace: str = "", regex: bool = False, doc: bool = False) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(find))
        self._table.setItem(row, 1, QTableWidgetItem(replace))

        regex_cb = QCheckBox()
        regex_cb.setChecked(regex)
        regex_cb.setStyleSheet("margin-left: 8px;")
        self._table.setCellWidget(row, 2, regex_cb)

        doc_cb = QCheckBox()
        doc_cb.setChecked(doc)
        doc_cb.setStyleSheet("margin-left: 8px;")
        doc_cb.setEnabled(self._doc_path is not None)
        self._table.setCellWidget(row, 3, doc_cb)

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)

    def page_title(self) -> str:
        return "Substitutions"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        self._table.setRowCount(0)
        for rule in cfg.substitutions.rules:
            self._add_row(find=rule.find, replace=rule.replace, regex=rule.regex, doc=False)
        if self._doc_path:
            for raw in _load_sidecar_raw(self._doc_path):
                find = raw.get("find", "")
                replace = raw.get("replace", "")
                regex = bool(raw.get("regex", False))
                if isinstance(find, str) and isinstance(replace, str) and find:
                    self._add_row(find=find, replace=replace, regex=regex, doc=True)

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        import re

        global_rules: list[SubstitutionRuleConfig] = []
        doc_rules: list[SubstitutionRuleConfig] = []

        for i in range(self._table.rowCount()):
            find_item = self._table.item(i, 0)
            replace_item = self._table.item(i, 1)
            regex_cb = self._table.cellWidget(i, 2)
            doc_cb = self._table.cellWidget(i, 3)

            find = find_item.text().strip() if find_item else ""
            replace = replace_item.text() if replace_item else ""
            use_regex = regex_cb.isChecked() if isinstance(regex_cb, QCheckBox) else False
            is_doc = doc_cb.isChecked() if isinstance(doc_cb, QCheckBox) else False

            if not find:
                continue
            if use_regex:
                try:
                    re.compile(find)
                except re.error as exc:
                    return f"Row {i + 1}: invalid regex {find!r}: {exc}"

            rule = SubstitutionRuleConfig(find=find, replace=replace, regex=use_regex)
            if is_doc:
                doc_rules.append(rule)
            else:
                global_rules.append(rule)

        cfg.substitutions.rules = global_rules

        if self._doc_path:
            try:
                _write_sidecar(self._doc_path, doc_rules)
            except OSError as exc:
                return f"Could not write document sidecar: {exc}"

        return None
