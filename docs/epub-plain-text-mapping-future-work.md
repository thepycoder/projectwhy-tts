# EPUB / QTextBrowser plain text mapping — follow-up options

**Context:** EPUB TTS blocks (`Block.text`) must align with `QTextBrowser.toPlainText()` for highlighting. **Option A** is implemented in `src/projectwhy/core/plain_qt.py` (`plain_text_like_qtextbrowser`, `normalize_plain_with_position_map`) and used by `core/epub.py` and `gui/text_view.py`.

This document summarizes **heavier** directions if duplication/fragility becomes a problem or if **word-level hover** (like PDF) is added.

---

## Option B — Post-layout index in the GUI (recommended next step)

**Idea:** Treat `QTextBrowser.document()` / `toPlainText()` after `setHtml` and layout as the **only** source of truth. Build indexes once per render:

1. `plain = browser.toPlainText()`
2. **`block_spans`:** global character `[start, end)` ranges per TTS block (same algorithm as today’s `_recompute_block_starts`, but centralized).
3. **`word_spans`:** per block, absolute `[start, end)` for each `block.words[i]` by walking the block substring in order (same semantics as `highlight_word_in_block`).

**Uses:**

- Playback highlight: direct cursor ranges, no repeated `find` in hot paths.
- **Word hover:** `cursorForPosition(mousePos).position()` → binary search on `block_spans` → find word in `word_spans[bi]` → `QTextCursor` / `cursorRect` for the hover box.

**Pros:** Matches Qt exactly; one rebuild on document reload/resize (already happens for theme/font/width).

**Cons:** Still fails if sequential substring search is ambiguous (duplicate identical blocks/phrases).

**Dependencies:** None beyond Qt; stays in `gui/` with optional shared normalization from `plain_qt.py`.

---

## Option C — Core precomputes offsets into a canonical plain string

**Idea:** At EPUB load, core builds a canonical string `P` (e.g. `"\n\n".join(block.text for ...)`) and records each block’s offset/length in `P`.

**Catch:** The UI shows **HTML**. Unless `toPlainText()` equals `P` **byte-for-byte**, stored offsets are wrong. Achieving that requires either reproducing Qt’s HTML→text in core (fragile), or **restricting** display to plain text / a fixed HTML shape.

**Pros:** Pure-core tests could validate offsets without a widget.

**Cons:** Poor fit for arbitrary publisher EPUB HTML + app CSS unless display is constrained.

**When to consider:** If the product moves to a **controlled** renderer where core owns the exact serialized plain text.

---

## Option D — Instrumented HTML (stable block/word anchors)

**Idea:** Emit HTML where each TTS block or word is wrapped in elements with stable attributes, e.g. `<span data-bi="3" data-wi="7">…</span>`, then query the document by fragment metadata.

**Reality check:** Publisher EPUB body HTML does not align with TTS block boundaries. Practical approaches are:

- **Generate** chapter HTML from the same `Block` list used for TTS (lose some original typography), or
- Hybrid sanitization + careful injection only where the DOM matches.

**Pros:** Strong mapping between TTS indices and DOM if HTML is owned end-to-end; could unify highlight + hover + future features.

**Cons:** Large pipeline change; must verify QTextBrowser preserves needed attributes through layout.

**When to consider:** If Option B proves insufficient and you **own** HTML generation from blocks.

---

## PDF vs EPUB mental model

- **PDF:** Hit-testing uses **geometry** (`WordPosition` / `BBox` in page space).
- **EPUB (QTextBrowser):** Ground truth is **character indices** in `QTextDocument` after layout. Option B maps indices → block/word; geometry for drawing comes from `QTextCursor` / layout, not from core `BBox`.

---

## References in repo

- `src/projectwhy/core/plain_qt.py` — Option A (shared normalization).
- `src/projectwhy/gui/text_view.py` — `_recompute_block_starts`, `highlight_word_in_block`.
- `src/projectwhy/gui/pdf_view.py` — reference for word hover via bbox hit-test.
