"""TTS engine, provider credentials, and highlight granularity."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from projectwhy.config import AppConfig, normalize_highlight_granularity


class VoiceSpeechSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Text-to-speech engine and how strongly the reader highlights the PDF or EPUB text."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        engine_box = QGroupBox("TTS engine")
        engine_form = QFormLayout(engine_box)
        self._engine = QComboBox()
        self._engine.addItem("Kokoro (local)", "kokoro")
        self._engine.addItem("OpenAI-compatible API", "openai")
        self._engine.addItem("Mistral Voxtral (cloud)", "mistral")
        self._engine.currentIndexChanged.connect(self._sync_engine_stack)
        engine_form.addRow("Engine:", self._engine)

        self._stack = QStackedWidget()

        kokoro_w = QWidget()
        kokoro_lay = QFormLayout(kokoro_w)
        self._kokoro_device = QLineEdit()
        self._kokoro_device.setPlaceholderText("cpu, cuda, … (empty = default)")
        kokoro_lay.addRow("Device:", self._kokoro_device)
        self._stack.addWidget(kokoro_w)

        openai_w = QWidget()
        openai_lay = QFormLayout(openai_w)
        self._openai_key = QLineEdit()
        self._openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_base = QLineEdit()
        self._openai_model = QLineEdit()
        self._openai_voice = QLineEdit()
        self._openai_format = QComboBox()
        for fmt in ("wav", "mp3"):
            self._openai_format.addItem(fmt)
        openai_lay.addRow("API key:", self._openai_key)
        openai_lay.addRow("Base URL:", self._openai_base)
        openai_lay.addRow("Model:", self._openai_model)
        openai_lay.addRow("Voice:", self._openai_voice)
        openai_lay.addRow("Format:", self._openai_format)
        self._stack.addWidget(openai_w)

        mistral_w = QWidget()
        mistral_outer = QVBoxLayout(mistral_w)
        mistral_form = QFormLayout()
        self._mistral_key = QLineEdit()
        self._mistral_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._mistral_model = QLineEdit()
        self._mistral_format = QComboBox()
        # Decoder in core only handles WAV (same as OpenAI path).
        self._mistral_format.addItem("wav")
        mistral_form.addRow("API key:", self._mistral_key)
        mistral_form.addRow("Model:", self._mistral_model)
        mistral_form.addRow("Audio format:", self._mistral_format)
        mistral_outer.addLayout(mistral_form)

        voice_row = QHBoxLayout()
        self._mistral_refresh = QPushButton("Refresh voice list")
        self._mistral_refresh.clicked.connect(self._on_refresh_mistral_voices)
        voice_row.addWidget(self._mistral_refresh)
        voice_row.addStretch(1)
        mistral_outer.addLayout(voice_row)

        mistral_form2 = QFormLayout()
        self._mistral_voice = QComboBox()
        mistral_form2.addRow("Voice:", self._mistral_voice)
        mistral_outer.addLayout(mistral_form2)
        mistral_outer.addStretch(1)
        self._stack.addWidget(mistral_w)

        outer.addWidget(engine_box)
        outer.addWidget(self._stack)

        highlight_box = QGroupBox("Highlight")
        hf = QFormLayout(highlight_box)
        self._highlight = QComboBox()
        self._highlight.addItem("Word-level (when TTS provides timings)", "word")
        self._highlight.addItem("Block-level (always)", "block")
        hf.addRow("Granularity:", self._highlight)
        outer.addWidget(highlight_box)
        outer.addStretch(1)

    def _sync_engine_stack(self, _idx: int | None = None) -> None:
        eng = self._engine.currentData()
        if eng == "openai":
            self._stack.setCurrentIndex(1)
        elif eng == "mistral":
            self._stack.setCurrentIndex(2)
        else:
            self._stack.setCurrentIndex(0)

    def page_title(self) -> str:
        return "Voice & speech"

    def widget(self) -> QWidget:
        return self._root

    def _on_refresh_mistral_voices(self) -> None:
        key = self._mistral_key.text().strip()
        if not key:
            QMessageBox.warning(self._root, "Voices", "Enter a Mistral API key first.")
            return
        model = self._mistral_model.text().strip() or "voxtral-mini-tts-2603"
        try:
            from projectwhy.core.tts.mistral_voxtral_tts import MistralVoxtralTTS

            t = MistralVoxtralTTS(api_key=key, model=model, voice_id="", response_format="wav")
            t.refresh_voices()
            ids = t.get_voices()
            labels = t.voice_labels()
        except RuntimeError as e:
            QMessageBox.warning(self._root, "Voices", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self._root, "Voices", f"Could not list voices:\n{e}")
            return

        self._mistral_voice.blockSignals(True)
        self._mistral_voice.clear()
        if labels is not None and len(labels) == len(ids):
            for label, vid in zip(labels, ids):
                self._mistral_voice.addItem(label, vid)
        else:
            for vid in ids:
                self._mistral_voice.addItem(vid, vid)
        self._mistral_voice.blockSignals(False)
        if not ids:
            QMessageBox.information(
                self._root,
                "Voices",
                "No voices returned. Create voices in Mistral Studio or the API, then refresh.",
            )

    def load_from_config(self, cfg: AppConfig) -> None:
        idx = self._engine.findData(cfg.tts.engine)
        self._engine.setCurrentIndex(max(0, idx))
        self._sync_engine_stack()

        self._kokoro_device.setText(cfg.tts.device or "")

        self._openai_key.setText(cfg.tts.openai.api_key)
        self._openai_base.setText(cfg.tts.openai.base_url)
        self._openai_model.setText(cfg.tts.openai.model)
        self._openai_voice.setText(cfg.tts.openai.voice)
        fmt_idx = self._openai_format.findText(cfg.tts.openai.format)
        self._openai_format.setCurrentIndex(max(0, fmt_idx))

        self._mistral_key.setText(cfg.tts.mistral.api_key)
        self._mistral_model.setText(cfg.tts.mistral.model)
        mf = self._mistral_format.findText(cfg.tts.mistral.format)
        self._mistral_format.setCurrentIndex(max(0, mf))
        self._mistral_voice.blockSignals(True)
        self._mistral_voice.clear()
        vid = cfg.tts.mistral.voice_id
        if vid:
            self._mistral_voice.addItem(vid[:16] + "…" if len(vid) > 16 else vid, vid)
            self._mistral_voice.setCurrentIndex(0)
        self._mistral_voice.blockSignals(False)

        h_idx = self._highlight.findData(cfg.display.highlight_granularity)
        self._highlight.setCurrentIndex(max(0, h_idx))

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        eng = str(self._engine.currentData())
        if eng == "mistral" and not self._mistral_key.text().strip():
            return "Mistral engine requires an API key."
        if eng == "openai" and not self._openai_key.text().strip():
            return "OpenAI engine requires an API key."

        cfg.tts.engine = eng
        cfg.tts.device = self._kokoro_device.text().strip()

        cfg.tts.openai.api_key = self._openai_key.text().strip()
        cfg.tts.openai.base_url = self._openai_base.text().strip()
        cfg.tts.openai.model = self._openai_model.text().strip()
        cfg.tts.openai.voice = self._openai_voice.text().strip()
        cfg.tts.openai.format = self._openai_format.currentText()

        cfg.tts.mistral.api_key = self._mistral_key.text().strip()
        cfg.tts.mistral.model = self._mistral_model.text().strip() or "voxtral-mini-tts-2603"
        cfg.tts.mistral.format = self._mistral_format.currentText()
        data = self._mistral_voice.currentData()
        cfg.tts.mistral.voice_id = str(data) if data is not None else ""

        cfg.display.highlight_granularity = normalize_highlight_granularity(
            str(self._highlight.currentData())
        )
        return None
