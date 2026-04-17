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

from projectwhy.config import AppConfig, SubstitutionRuleConfig, clamp_epub_font_size, save
from projectwhy.core.document import load_document
from projectwhy.core.pdf import block_hit_at_page_point, word_hit_at_page_point
from projectwhy.core.player import AudioPlayer
from projectwhy.core.models import Block
from projectwhy.core.session import ReadingSession, merged_block_config, speak_heuristic
from projectwhy.core.sidecar import load_reading_position, save_reading_position
from projectwhy.core.substitutions import SubstitutionRule, parse_rules
from projectwhy.core.tts.base import TTSEngine
from projectwhy.gui.controls import ControlBar
from projectwhy.gui.inspector.dock import InspectorDock
from projectwhy.gui.settings import SettingsDialog
from projectwhy.gui.pdf_view import PDFView
from projectwhy.gui.audiobook_dialog import AudiobookDialog
from projectwhy.gui.text_view import TextDocView

logger = logging.getLogger(__name__)


def _tts_config_fingerprint(cfg: AppConfig) -> tuple:
    m, o = cfg.tts.mistral, cfg.tts.openai
    return (
        cfg.tts.engine,
        cfg.tts.voice,
        cfg.tts.device,
        o.api_key,
        o.base_url,
        o.model,
        o.voice,
        o.format,
        m.api_key,
        m.model,
        m.voice_id,
        m.format,
    )


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
        self._last_epub_focus: tuple[int, int] | None = None

        self.setWindowTitle("projectwhy-tts")
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._pdf_view = PDFView()
        self._pdf_view.setStatusTip("Click a word to start reading; drag to pan the page")
        self._pdf_view.set_hover_granularity(self.cfg.display.highlight_granularity)
        self._pdf_view.set_highlight_color(self.cfg.display.highlight_color)
        self._pdf_view.word_clicked.connect(self._on_pdf_word_click)
        self._text_view = TextDocView()
        self._sync_text_reader_from_config()
        self._stack.addWidget(self._pdf_view)
        self._stack.addWidget(self._text_view)

        self._controls = ControlBar()
        self._apply_voice_combo(tts)
        self._controls.set_playback_speed(cfg.reading.playback_speed)
        self.statusBar().addPermanentWidget(self._controls, stretch=1)

        self._controls.play_clicked.connect(self._on_play)
        self._controls.pause_clicked.connect(self._on_pause)
        self._controls.prev_page_clicked.connect(self._on_prev)
        self._controls.next_page_clicked.connect(self._on_next)
        self._controls.page_jump_requested.connect(self._on_page_jump)
        self._controls.prev_block_clicked.connect(self._on_prev_block)
        self._controls.next_block_clicked.connect(self._on_next_block)
        self._controls.voice_changed.connect(self._on_voice_changed)
        self._controls.speed_changed.connect(self._on_speed)
        self._controls.epub_font_smaller_clicked.connect(self._on_epub_font_smaller)
        self._controls.epub_font_larger_clicked.connect(self._on_epub_font_larger)

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

    def _sync_text_reader_from_config(self) -> None:
        d = self.cfg.display
        self._text_view.set_highlight_color(d.highlight_color)
        self._text_view.apply_reader_settings(
            d.epub_theme,
            d.epub_font_size,
            d.epub_line_height,
            d.epub_column_max_width,
        )

    def _on_epub_font_smaller(self) -> None:
        self.cfg.display.epub_font_size = clamp_epub_font_size(self.cfg.display.epub_font_size - 1)
        self._text_view.set_font_size(self.cfg.display.epub_font_size)

    def _on_epub_font_larger(self) -> None:
        self.cfg.display.epub_font_size = clamp_epub_font_size(self.cfg.display.epub_font_size + 1)
        self._text_view.set_font_size(self.cfg.display.epub_font_size)

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
        self._audiobook_action = m.addAction("Generate audiobook…")
        self._audiobook_action.triggered.connect(self._menu_audiobook)
        self._audiobook_action.setEnabled(False)
        a_settings = m.addAction("Settings…")
        a_settings.triggered.connect(self._menu_settings)

        view = self.menuBar().addMenu("View")
        self._inspector_action = view.addAction("Inspector")
        self._inspector_action.setCheckable(True)
        self._inspector_action.toggled.connect(self._inspector.setVisible)
        self._inspector.visibilityChanged.connect(self._inspector_action.setChecked)

    def _menu_audiobook(self) -> None:
        if not self.session or self.session.document.doc_type != "epub":
            QMessageBox.information(
                self,
                "Audiobook",
                "Open an EPUB document to generate an audiobook.",
            )
            return
        dlg = AudiobookDialog(self.cfg, self.session, self.tts, self)
        dlg.exec()

    def _menu_settings(self) -> None:
        doc_path = self.session.document.path if self.session else None
        tts_fp_before = _tts_config_fingerprint(self.cfg)
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
            self.session.set_highlight_granularity(self.cfg.display.highlight_granularity)
        self._pdf_view.set_hover_granularity(self.cfg.display.highlight_granularity)
        self._controls.set_playback_speed(self.cfg.reading.playback_speed)

        if _tts_config_fingerprint(self.cfg) != tts_fp_before:
            self.tts = create_tts(self.cfg)
            if self.session:
                self.session.set_tts_engine(self.tts)
            self._apply_voice_combo(self.tts)

        self._pdf_view.set_highlight_color(self.cfg.display.highlight_color)
        self._sync_text_reader_from_config()
        if self.session and self.session.document.doc_type != "pdf":
            p = self.session.current_page()
            t = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._text_view.set_document_text(t, p.blocks, p.html)

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
            self._save_reading_position()
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
            highlight_granularity=self.cfg.display.highlight_granularity,
        )
        self._last_poll_page = -1
        self._last_epub_focus = None
        self._inspector.reset()

        total = len(doc.pages)
        self._controls.set_page_indicator(0, total)

        if doc.doc_type == "pdf":
            self._controls.set_epub_font_controls_visible(False)
            self._stack.setCurrentWidget(self._pdf_view)
            try:
                saved = load_reading_position(path, len(doc.pages))
                if saved is not None:
                    self.session.go_to_position(*saved)
                else:
                    self.session.go_to_page(0)
                p = self.session.current_page()
                if p.image is not None:
                    self._pdf_view.set_page_image(p.image)
            except Exception as e:  # noqa: BLE001
                logger.exception("page render")
                QMessageBox.warning(self, "Page load", str(e))
        else:
            self._controls.set_epub_font_controls_visible(True)
            self._stack.setCurrentWidget(self._text_view)
            saved = load_reading_position(path, len(doc.pages))
            if saved is not None:
                self.session.go_to_position(*saved)
            else:
                self.session.go_to_page(0)
            p = self.session.current_page()
            text = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._sync_text_reader_from_config()
            self._text_view.set_document_text(text, p.blocks, p.html)

        self._poll.start()
        self._audiobook_action.setEnabled(doc.doc_type == "epub")
        if doc.doc_type == "pdf":
            self._pdf_view.set_hover_granularity(self.cfg.display.highlight_granularity)

    def _apply_voice_combo(self, tts: TTSEngine) -> None:
        names = tts.get_voices()
        labels = getattr(tts, "voice_labels", None)
        if callable(labels):
            labels = labels()
        current = getattr(tts, "voice", None)
        if labels is not None and len(labels) == len(names) and names:
            self._controls.set_voices(labels, current=current, voice_values=names)
        else:
            self._controls.set_voices(names, current=current)

    def _on_pdf_word_click(self, x: float, y: float) -> None:
        if not self.session or self.session.document.doc_type != "pdf":
            return
        p = self.session.current_page()
        if p.image is None:
            return
        w, h = p.image.size
        if not (0 <= x < w and 0 <= y < h):
            return
        if self.cfg.display.highlight_granularity == "block":
            bi = block_hit_at_page_point(p, x, y)
            if bi is None:
                return
            self.session.play_from_pdf_block(self.session.page_index, bi)
            return
        hit = word_hit_at_page_point(p, x, y)
        if hit is None:
            return
        bi, wi = hit
        self.session.play_from_pdf_word(self.session.page_index, bi, wi)

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

    def _on_voice_changed(self, v: str) -> None:
        if self.cfg.tts.engine == "mistral":
            self.cfg.tts.mistral.voice_id = v
        elif self.cfg.tts.engine == "openai":
            self.cfg.tts.openai.voice = v
        else:
            self.cfg.tts.voice = v
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
            self._pdf_view.set_hover_blocks(p.blocks)
            if p.image is not None:
                self._pdf_view.set_page_image(p.image)
        else:
            p = self.session.current_page()
            text = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._text_view.set_document_text(text, p.blocks, p.html)

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

        if doc.doc_type != "pdf" and current_pi != self._last_poll_page:
            self._last_poll_page = current_pi
            p = self.session.current_page()
            text = p.raw_text or "\n\n".join(b.text for b in p.blocks)
            self._text_view.set_document_text(text, p.blocks, p.html)

        bbox = self.session.get_active_word_bbox()
        block = self.session.get_active_block()
        st = self.session.get_state()

        if doc.doc_type == "pdf":
            page = self.session.current_page()
            self._pdf_view.set_hover_blocks(page.blocks)
            self._pdf_view.set_highlight_bbox(bbox)
            self._last_epub_focus = None
        else:
            focus = (st.page_index, st.block_index)
            recenter = focus != self._last_epub_focus
            if st.is_playing:
                self._text_view.highlight_word_in_block(
                    block,
                    st.word_index,
                    block_index=st.block_index,
                    scroll_into_view=recenter,
                )
            else:
                self._text_view.highlight_word_in_block(
                    self.session.get_cursor_block(),
                    None,
                    block_index=st.block_index,
                    scroll_into_view=recenter,
                )
            self._last_epub_focus = focus

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

    def _save_reading_position(self) -> None:
        if self.session is None:
            return
        doc = self.session.document
        try:
            save_reading_position(doc.path, self.session.page_index, self.session.block_index)
        except Exception:
            logger.exception("failed to save reading position for %s", doc.path)

    def closeEvent(self, e) -> None:  # noqa: ANN001
        self._poll.stop()
        if self.session:
            self._save_reading_position()
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
    if cfg.tts.engine == "mistral":
        from projectwhy.core.tts.mistral_voxtral_tts import MistralVoxtralTTS

        m = cfg.tts.mistral
        return MistralVoxtralTTS(
            api_key=m.api_key,
            model=m.model,
            voice_id=m.voice_id,
            response_format=m.format,
        )
    from projectwhy.core.tts.kokoro_tts import KokoroTTS

    return KokoroTTS(
        voice=cfg.tts.voice,
        device=cfg.tts.device or None,
    )
