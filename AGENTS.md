# AGENTS.md — projectwhy-tts

## What this is

A KISS desktop PDF/EPUB reader with baked-in TTS and word-level highlighting.
No web server, no API, no database — just a Python app you run locally.

## Architecture

Two layers, strictly separated:

- **`core/`** — all logic: document loading, layout analysis, TTS, audio playback, session orchestration. Zero GUI imports. This is the API surface a future web interface would consume.
- **`gui/`** — PyQt6 presentation only. Calls into `core/` via `ReadingSession`. Never put business logic here.

The boundary is `core/session.py` → `ReadingSession`. The GUI polls `get_state()` / `get_active_word_bbox()` on a 33ms QTimer. All playback, TTS, and document state lives in core.

## Key design decisions

- **Kokoro TTS runs in-process** (no API server). Word timestamps come free from the synthesis forward pass — no whisper/alignment step.
- **DocLayout-YOLO** detects semantic regions (title, paragraph, figure, table, etc.) on each PDF page. Text is extracted per-region, not blindly from the whole page. This drives reading order, skip/speak decisions, and scoped word highlighting.
- **pypdfium2** (Apache 2.0) for PDF rendering and character-level text extraction.
- **sounddevice** for audio playback with frame-counting position tracking.
- **UV** for dependency management (`uv sync`, `uv run projectwhy`).

## Data flow (PDF)

```
pypdfium2 renders page → PIL Image
                           ├→ DocLayout-YOLO detects typed regions (blocks)
pypdfium2 extracts chars → words assigned into blocks → reading order sort
                           ↓
Kokoro synthesizes block text → audio + word_timestamps
                           ↓
sounddevice plays audio → frame counter tracks position
                           ↓
GUI polls position → matches to word timestamp → highlights word bbox on page
```

## Rules for working in this repo

1. **Keep it simple.** No premature abstractions, no deep class hierarchies. Flat is better than nested.
2. **Core must never import from gui.** GUI depends on core, never the reverse.
3. **Don't add dependencies without a strong reason.** Check the license (no AGPL/GPL).
4. **No elaborate error handling yet.** Let exceptions propagate naturally. Clean, readable code over defensive code.
5. **Block behavior is configurable** — titles get paused after, figures/tables get skipped. See `BLOCK_CONFIG` in `core/session.py`.
6. **Use ruff** for linting (line-length 100). Run `uv run ruff check`.
7. **Readability** a naive, but straighforward logical approach is better than a prematurely optimized mess. Both structurally and syntax-wise, engineer for understandability and maintainability.
