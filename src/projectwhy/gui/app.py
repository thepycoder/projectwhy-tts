"""Main PyQt6 application window."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from projectwhy.config import AppConfig, SubstitutionRuleConfig, save
from projectwhy.core.document import load_document
from projectwhy.core.player import AudioPlayer
from projectwhy.core.models import Block
from projectwhy.core.session import ReadingSession, merged_block_config, speak_heuristic
from projectwhy.core.substitutions import SubstitutionRule, parse_rules
from projectwhy.core.tts.base import TTSEngine
from projectwhy.gui.controls import ControlBar
from projectwhy.gui.inspector.dock import InspectorDock
from projectwhy.gui.settings import SettingsDialog
from projectwhy.gui.pdf_view import PDFView
from projectwhy.gui.text_view import TextDocView

logger = logging.getLogger(__name__)


def _rules_from_config(rule_configs: list[SubstitutionRuleConfig]) -> list[SubstitutionRule]:
    raw = [{"find": r.find, "replace": r.replace, "regex": r.regex} for r in rule_configs]
    try:
        return parse_rules(raw)
    except ValueError:
        logger.exception("invalid substitution rules in config — rules disabled")
        return []


def _load_sidecar_rules(doc_path: str) -> list[SubstitutionRule]:
    """Load substitution rules from an optional sidecar file next to the document.

    The sidecar file is named ``<doc_path>.projectwhy.toml`` and must contain
    a ``[substitutions]`` section with the same ``rules`` shape as global config.
    A missing file is silently ignored; a parse error is logged and yields no rules.
    """
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
        logger.exception("failed to load sidecar %s — rules disabled", sidecar)
        return []


class MainWindow(QMainWindow):
    def __init__(
        self,
        cfg: AppConfig,
        tts: TTSEngine,
        layout_model,
        initial_path: str | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.tts = tts
        self.layout_model = layout_model
        self._config_path = config_path
        self.player = AudioPlayer()
        self.session: ReadingSession | None = None
        self._pdf = None
        self._last_poll_page: int = -1

        self.setWindowTitle("projectwhy-tts")
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._pdf_view = PDFView()
        self._text_view = TextDocView()
        self._stack.addWidget(self._pdf_view)
        self._stack.addWidget(self._text_view)

        self._controls = ControlBar()
        self._controls.set_voices(tts.get_voices(), getattr(tts, "voice", None))
        self._controls.set_playback_speed(cfg.reading.playback_speed)
        self.statusBar().addPermanentWidget(self._controls, stretch=1)

        self._controls.play_clicked.connect(self._on_play)
        self._controls.pause_clicked.connect(self._on_pause)
        self._controls.prev_page_clicked.connect(self._on_prev)
        self._controls.next_page_clicked.connect(self._on_next)
        self._controls.page_jump_requested.connect(self._on_page_jump)
        self._controls.prev_block_clicked.connect(self._on_prev_block)
        self._controls.next_block_clicked.connect(self._on_next_block)
        self._controls.voice_changed.connect(self._on_voice)
        self._controls.speed_changed.connect(self._on_speed)

        self._poll = QTimer(self)
        self._poll.setInterval(33)
        self._poll.timeout.connect(self._on_poll)

        self._inspector = InspectorDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._inspector)
        self._inspector.overlay_toggled.connect(self._pdf_view.set_show_overlays)
        self._inspector.hide()

        self._create_menus()

        if initial_path:
            self.open_path(initial_path)

    def _inspector_speak_check(self, block: Block) -> bool:
        if self.session is not None:
            return self.session.would_speak(block)
        return speak_heuristic(block, merged_block_config(self.cfg.blocks.types))

    def _inspector_tts_text(self, block: Block) -> str:
        if self.session is not None:
            return self.session.get_tts_text_for_block(block)
        return block.text

    def _create_menus(self) -> None:
        m = self.menuBar().addMenu("File")
        a_open = m.addAction("Open…")
        a_open.triggered.connect(self._menu_open)
        a_settings = m.addAction("Settings…")
        a_settings.triggered.connect(self._menu_settings)

        view = self.menuBar().addMenu("View")
        self._inspector_action = view.addAction("Inspector")
        self._inspector_action.setCheckable(True)
        self._inspector_action.toggled.connect(self._inspector.setVisible)
        self._inspector.visibilityChanged.connect(self._inspector_action.setChecked)

    def _menu_settings(self) -> None:
        doc_path = self.session.document.path if self.session else None
        dlg = SettingsDialog(self.cfg, self, doc_path=doc_path)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = self._config_path or Path.cwd() / "config.toml"
        try:
            save(path, self.cfg)
        except OSError as e:
            logger.exception("save config")
            QMessageBox.warning(self, "Settings", f"Could not save config:\n{e}")
            return
        if self.session:
            self.session.set_playback_settings(
                self.cfg.reading.tts_cache_max_entries,
                self.cfg.reading.prefetch_lookahead,
                self.cfg.reading.playback_speed,
            )
            self.session.set_pdf_text(self.cfg.pdf_text)
            self.session.set_block_config(merged_block_config(self.cfg.blocks.types))
            global_rules = _rules_from_config(self.cfg.substitutions.rules)
            sidecar_rules = _load_sidecar_rules(self.session.document.path)
            self.session.set_substitution_rules(global_rules + sidecar_rules)
        self._controls.set_playback_speed(self.cfg.reading.playback_speed)

    def _menu_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open document",
            str(Path.home()),
            "Documents (*.pdf *.epub *.txt *.md);;All (*)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if self.session:
            self.session.stop()
        try:
            if self._pdf is not None:
                self._pdf.close()
                self._pdf = None
            doc, self._pdf = load_document(path)
        except Exception as e:  # noqa: BLE001
            logger.exception("open failed")
            QMessageBox.critical(self, "Open failed", str(e))
            return

        global_rules = _rules_from_config(self.cfg.substitutions.rules)
        sidecar_rules = _load_sidecar_rules(path)
        merged_rules = global_rules + sidecar_rules

        self.session = ReadingSession(
            doc,
            self._pdf,
            self.tts,
            self.player,
            layout_model=self.layout_model,
            pdf_scale=self.cfg.display.pdf_scale,
            tts_cache_max_entries=self.cfg.reading.tts_cache_max_entries,
            prefetch_lookahead=self.cfg.reading.prefetch_lookahead,
            playback_speed=self.cfg.reading.playback_speed,
            pdf_text=self.cfg.pdf_text,
            block_config=merged_block_config(self.cfg.blocks.types),
            substitution_rules=merged_rules,
        )
        self._last_poll_page = -1
        self._inspector.reset()

        total = len(doc.pages)
        self._controls.set_page_indicator(0, total)

        if doc.doc_type == "pdf":
            self._stack.setCurrentWidget(self._pdf_view)
            try:
                self.session.go_to_page(0)
                p = self.session.current_page()
                if p.image is not None:
                    self._pdf_view.set_page_image(p.image)
            except Exception as e:  # noqa: BLE001
                logger.exception("page render")
                QMessageBox.warning(self, "Page load", str(e))
        else:
            self._stack.setCurrentWidget(self._text_view)
            self.session.go_to_page(0)
            p = self.session.current_page()
            text = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._text_view.set_document_text(text, p.blocks)

        self._poll.start()

    def _on_play(self) -> None:
        if self.session:
            self.session.play()

    def _on_pause(self) -> None:
        if self.session:
            self.session.pause()

    def _on_prev(self) -> None:
        if not self.session:
            return
        self.session.stop()
        self.session.prev_page()
        self._refresh_page_view()

    def _on_next(self) -> None:
        if not self.session:
            return
        self.session.stop()
        self.session.next_page()
        self._refresh_page_view()

    def _on_page_jump(self, page_index: int) -> None:
        if not self.session:
            return
        doc = self.session.document
        if page_index < 0 or page_index >= len(doc.pages):
            return
        self.session.stop()
        self.session.go_to_page(page_index)
        self._refresh_page_view()

    def _on_prev_block(self) -> None:
        if not self.session:
            return
        self.session.prev_speakable_block()
        if self.session.is_active:
            self.session.interrupt_playback()
        self._refresh_page_view()

    def _on_next_block(self) -> None:
        if not self.session:
            return
        self.session.next_speakable_block()
        if self.session.is_active:
            self.session.interrupt_playback()
        self._refresh_page_view()

    def _on_voice(self, v: str) -> None:
        if self.session:
            self.session.set_voice(v)

    def _on_speed(self, s: float) -> None:
        self.cfg.reading.playback_speed = float(s)
        if self.session:
            self.session.set_speed(s)

    def _refresh_page_view(self) -> None:
        if not self.session:
            return
        doc = self.session.document
        self._controls.set_page_indicator(self.session.page_index, len(doc.pages))
        if doc.doc_type == "pdf":
            p = self.session.current_page()
            if p.image is not None:
                self._pdf_view.set_page_image(p.image)
        else:
            p = self.session.current_page()
            text = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._text_view.set_document_text(text, p.blocks)

        if self._inspector.isVisible():
            p = self.session.current_page()
            st = self.session.get_state()
            self._inspector.update_page(
                p, st, speak_check=self._inspector_speak_check, tts_text_fn=self._inspector_tts_text
            )
            if doc.doc_type == "pdf":
                self._pdf_view.set_block_overlays(p.blocks, st.block_index)

    def _on_poll(self) -> None:
        if not self.session:
            return
        doc = self.session.document
        current_pi = self.session.page_index
        self._controls.set_page_indicator(current_pi, len(doc.pages))

        if doc.doc_type == "pdf" and current_pi != self._last_poll_page:
            self._last_poll_page = current_pi
            p = self.session.current_page()
            if p.image is not None:
                self._pdf_view.set_page_image(p.image)

        bbox = self.session.get_active_word_bbox()
        block = self.session.get_active_block()
        st = self.session.get_state()

        if doc.doc_type == "pdf":
            self._pdf_view.set_highlight_bbox(bbox)
        else:
            if st.is_playing:
                self._text_view.highlight_word_in_block(block, st.word_index)
            else:
                self._text_view.highlight_word_in_block(self.session.get_cursor_block(), None)

        if self._inspector.isVisible():
            page = self.session.current_page()
            self._inspector.update_page(
                page, st, speak_check=self._inspector_speak_check, tts_text_fn=self._inspector_tts_text
            )
            if doc.doc_type == "pdf":
                self._pdf_view.set_block_overlays(page.blocks, st.block_index)
            w = self.session.warmer
            self._inspector.update_pipeline(w.peek_snapshot() if w else [])
        else:
            self._pdf_view.set_show_overlays(False)
            self._pdf_view.set_block_overlays([], None)

    def closeEvent(self, e) -> None:  # noqa: ANN001
        self._poll.stop()
        if self.session:
            self.session.stop()
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(e)


def create_tts(cfg: AppConfig):
    if cfg.tts.engine == "openai":
        from projectwhy.core.tts.openai_tts import OpenAITTS

        return OpenAITTS(
            api_key=cfg.tts.openai.api_key,
            base_url=cfg.tts.openai.base_url,
            model=cfg.tts.openai.model,
            voice=cfg.tts.openai.voice,
            response_format=cfg.tts.openai.format,
        )
    from projectwhy.core.tts.kokoro_tts import KokoroTTS

    return KokoroTTS(
        voice=cfg.tts.voice,
        device=cfg.tts.device or None,
    )
