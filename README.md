# projectwhy-tts

**Read PDFs and EPUBs on your desktop with built-in text-to-speech—no server, no account, no cloud.**

projectwhy-tts is a small, local reader that combines page rendering, [PP-DocLayout](https://github.com/PaddlePaddle/PaddleOCR) region detection on PDFs, and [Kokoro](https://github.com/hexgrad/kokoro) TTS with word- and block-level highlighting. You open a file, press play, and listen while the current word or region stays visible on screen.

> This repo was coded almost exclusively by an AI agent in my spare time, but the code was heavily reviewed, architectural design was thought through, and the choices were mine. I would not call this production grade, but it isn’t vibe-coded either.

---

## Screenshots

![PDF open in projectwhy-tts with playback controls along the bottom](https://raw.githubusercontent.com/thepycoder/projectwhy-tts/master/docs/readme/reading-view.png)

*PDF reading: multi-column layout, voice and speed controls, page and block navigation.*

![PDF with a highlighted layout block and the view scrolled to the current region](https://raw.githubusercontent.com/thepycoder/projectwhy-tts/master/docs/readme/block-navigation.png)

*Layout-aware navigation: the model detects semantic regions; use **Prev block** / **Next block** to move through titles, paragraphs, and other blocks. Highlights follow what is being read.*

![Inspector on a PDF: Layout tab with block index, type, text preview, and Speak or Skip; color-coded overlays](https://raw.githubusercontent.com/thepycoder/projectwhy-tts/master/docs/readme/pdf-inspector.png)

**Inspector** (**View → Inspector**): the **Layout** tab lists each detected region with its **Type** (color-coded; overlays optional). On this page you mostly see `text` and a `footer`; other PDFs will surface titles, tables, figures, formulas, and more. **Speak** vs **Skip** follows your block-type settings. See `BlockType` in `src/projectwhy/core/models.py` for the full label set.

![EPUB chapter with typography controls and the same playback bar](https://raw.githubusercontent.com/thepycoder/projectwhy-tts/master/docs/readme/epub-view.png)

*EPUBs: reflowable text, theme and font size (**A−** / **A+**), same listening workflow as PDFs.*

---

## Why use it?

- **Offline-first** — Runs entirely on your machine; documents stay local.
- **Readable PDFs** — Regions come from layout detection (not one giant text dump), which drives reading order and skip/speak behavior.
- **Natural listening** — Kokoro synthesizes in-process; timestamps line up with words on the page for highlighting.
- **Simple stack** — PyQt6 UI, Python `core/` logic separate from `gui/`, configuration via TOML.

---

## Quick start

```bash
git clone https://github.com/thepycoder/projectwhy-tts.git
cd projectwhy-tts
uv venv
uv sync
```

Copy `config.example.toml` to `config.toml` and adjust voices, layout model, or display options.

```bash
uv run projectwhy path/to/book.pdf
uv run projectwhy path/to/book.epub
```

---

## First run

The first launch downloads **Kokoro** weights (via Hugging Face) and **PP-DocLayout** weights (via the PaddleX cache under `~/.paddlex`; size depends on the S/M/L variant you choose in config). Expect a short wait once.

On some Linux CPU builds, Paddle oneDNN can misbehave; the example config sets `enable_mkldnn = false`. You can set `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` to skip PaddleX’s model-host connectivity check at import time.

---

## Requirements

- **Python 3.11+**
- **Audio output** (speakers or headphones)
- **[Rubber Band](https://breakfastquay.com/rubberband/)** via [pyrubberband](https://github.com/bmcfee/pyrubberband): install the **rubberband** CLI on your OS (for example Arch `rubberband`, Debian/Ubuntu `rubberband-cli`) so `rubberband` is on `PATH`, if you want playback speeds other than **1.0×** with pitch-preserving tempo.
- **Optional:** GPU for faster layout (`[layout] device = "gpu"` in `config.toml`) and for Kokoro; CPU works for typical use.

---

## Configuration

All options live in `config.toml`. The main sections are **`[tts]`** (engine, voice, device), **`[layout]`** (PP-DocLayout model size, confidence, CPU/GPU), **`[display]`** (PDF scale, highlights, EPUB theme and font), **`[reading]`** (cache, lookahead, default speed), and **`[substitutions]`** (optional find/replace before synthesis). See `config.example.toml` for every key.

---

## Architecture (short)

- **`core/`** — Document loading, layout, TTS, audio, session state. No GUI imports.
- **`gui/`** — PyQt6 only; talks to `core` through `ReadingSession`.

For deeper design notes, see [`AGENTS.md`](AGENTS.md).

---

## License

This project is offered under the terms of its repository license. Dependencies (models and libraries) remain under their respective licenses.
