"""Dialog: EPUB → M4B audiobook generation with progress and cancel."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QDialog,
    QWidget,
)

from projectwhy.config import AppConfig, SubstitutionRuleConfig
from projectwhy.core.audiobook import (
    AudiobookError,
    AudiobookMetadata,
    AudiobookProgress,
    generate_audiobook,
)
from projectwhy.core.session import ReadingSession, merged_block_config
from projectwhy.core.substitutions import SubstitutionRule, parse_rules
from projectwhy.core.tts.base import TTSEngine

logger = logging.getLogger(__name__)


def _rules_from_config(rule_configs: list[SubstitutionRuleConfig]) -> list[SubstitutionRule]:
    raw = [{"find": r.find, "replace": r.replace, "regex": r.regex} for r in rule_configs]
    try:
        return parse_rules(raw)
    except ValueError:
        logger.exception("invalid substitution rules in config")
        return []


def _load_sidecar_rules(doc_path: str) -> list[SubstitutionRule]:
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
        return parse_rules(raw)
    except Exception:
        logger.exception("failed to load sidecar %s", sidecar)
        return []


def _voice_summary(cfg: AppConfig, tts: TTSEngine) -> str:
    if cfg.tts.engine == "openai":
        return f"{cfg.tts.openai.model} / {cfg.tts.openai.voice}"
    if cfg.tts.engine == "mistral":
        vid = cfg.tts.mistral.voice_id or "(unset)"
        return f"{cfg.tts.mistral.model} / {vid[:12]}…" if len(vid) > 12 else f"{cfg.tts.mistral.model} / {vid}"
    return str(getattr(tts, "voice", cfg.tts.voice))


class AudiobookWorker(QThread):
    progress = pyqtSignal(object)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        document,
        tts: TTSEngine,
        output_path: Path,
        block_config,
        substitution_rules: list[SubstitutionRule],
        metadata: AudiobookMetadata,
        cancel_event: threading.Event,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._tts = tts
        self._output_path = output_path
        self._block_config = block_config
        self._substitution_rules = substitution_rules
        self._metadata = metadata
        self._cancel_event = cancel_event

    def run(self) -> None:
        try:
            generate_audiobook(
                self._document,
                self._tts,
                self._output_path,
                block_config=self._block_config,
                substitution_rules=self._substitution_rules,
                metadata=self._metadata,
                progress_cb=self.progress.emit,
                cancel_event=self._cancel_event,
            )
            if self._cancel_event.is_set():
                self.failed.emit("Cancelled.")
                return
            self.finished_ok.emit(str(self._output_path))
        except AudiobookError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class AudiobookDialog(QDialog):
    """EPUB → M4B export with progress and cancel."""

    def __init__(
        self,
        cfg: AppConfig,
        session: ReadingSession,
        tts: TTSEngine,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate audiobook")
        self.setMinimumWidth(520)
        self.cfg = cfg
        self.session = session
        self.tts = tts
        self._cancel_event = threading.Event()
        self._worker: AudiobookWorker | None = None

        doc = session.document
        default_out = Path(doc.path).with_suffix(".m4b")

        root = QVBoxLayout(self)
        summary = QGroupBox("Generation settings (from Settings)")
        sf = QFormLayout(summary)
        global_rules = _rules_from_config(cfg.substitutions.rules)
        sidecar_rules = _load_sidecar_rules(doc.path)
        n_rules = len(global_rules) + len(sidecar_rules)
        sf.addRow("Engine:", QLabel(str(cfg.tts.engine)))
        sf.addRow("Voice:", QLabel(_voice_summary(cfg, tts)))
        sf.addRow("Audiobook tempo:", QLabel("1.0× (native TTS; ignores in-app speed)"))
        sf.addRow("Substitution rules:", QLabel(str(n_rules)))
        root.addWidget(summary)

        out_row = QHBoxLayout()
        self._out_edit = QLineEdit(str(default_out))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_out)
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(browse)
        root.addLayout(out_row)

        self._overall = QProgressBar()
        self._overall.setRange(0, 100)
        self._chapter = QProgressBar()
        self._chapter.setRange(0, 100)
        root.addWidget(QLabel("Overall progress"))
        root.addWidget(self._overall)
        root.addWidget(QLabel("Current chapter"))
        root.addWidget(self._chapter)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._btn_generate = QPushButton("Generate")
        self._btn_generate.clicked.connect(self._start)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_generate)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save audiobook as",
            self._out_edit.text(),
            "Audiobook (*.m4b);;All (*)",
        )
        if path:
            if not path.lower().endswith(".m4b"):
                path += ".m4b"
            self._out_edit.setText(path)

    def _metadata(self) -> AudiobookMetadata:
        doc = self.session.document
        meta = doc.metadata or {}
        title = str(meta.get("title") or Path(doc.path).stem)
        author = meta.get("author")
        author_s = str(author).strip() if author else None
        cover_bytes = meta.get("cover_bytes")
        cover_mime = meta.get("cover_mime")
        cb = bytes(cover_bytes) if isinstance(cover_bytes, (bytes, bytearray)) else None
        cm = str(cover_mime) if cover_mime else None
        return AudiobookMetadata(
            title=title,
            author=author_s,
            cover_bytes=cb,
            cover_mime=cm,
        )

    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._cancel_event.clear()
        out = Path(self._out_edit.text().strip())
        if not out.parent.is_dir():
            QMessageBox.warning(self, "Audiobook", "Output folder does not exist.")
            return

        doc = self.session.document
        global_rules = _rules_from_config(self.cfg.substitutions.rules)
        sidecar_rules = _load_sidecar_rules(doc.path)
        merged_rules = global_rules + sidecar_rules
        block_cfg = merged_block_config(self.cfg.blocks.types)

        self._worker = AudiobookWorker(
            document=doc,
            tts=self.tts,
            output_path=out,
            block_config=block_cfg,
            substitution_rules=merged_rules,
            metadata=self._metadata(),
            cancel_event=self._cancel_event,
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_done)

        self._overall.setValue(0)
        self._chapter.setValue(0)
        self._status.setText("Starting…")
        self._btn_generate.setEnabled(False)
        self._btn_close.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._worker.start()

    def _cancel(self) -> None:
        self._cancel_event.set()
        self._status.setText("Cancelling…")

    def _on_worker_done(self) -> None:
        self._btn_generate.setEnabled(True)
        self._btn_close.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._worker = None

    def _on_progress(self, p: AudiobookProgress) -> None:
        n = max(1, p.total_chapters)
        if p.phase == "encoding":
            self._overall.setValue(99)
            self._chapter.setValue(100)
            self._status.setText("Encoding M4B with ffmpeg…")
            return
        if p.phase == "done":
            self._overall.setValue(100)
            self._chapter.setValue(100)
            self._status.setText("Done.")
            return
        if p.phase == "cancelled":
            self._status.setText("Cancelled.")
            return
        tb = max(1, p.total_blocks)
        chap_frac = p.block_index / float(tb)
        overall = int(100 * (p.chapter_index + chap_frac) / float(n))
        self._overall.setValue(min(99, overall))
        self._chapter.setValue(int(100 * chap_frac))
        cache = " (cached)" if p.skipped_cached else ""
        self._status.setText(
            f"Synthesizing chapter {p.chapter_index + 1}/{n}: {p.chapter_title}{cache} — "
            f"block {p.block_index}/{tb} — {p.elapsed_sec:.0f}s elapsed"
        )

    def _on_finished_ok(self, path: str) -> None:
        self._overall.setValue(100)
        self._chapter.setValue(100)
        self._status.setText(f"Saved: {path}")
        QMessageBox.information(self, "Audiobook", f"Audiobook saved to:\n{path}")

    def _on_failed(self, msg: str) -> None:
        self._status.setText(msg)
        if msg != "Cancelled.":
            QMessageBox.warning(self, "Audiobook", msg)
