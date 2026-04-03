# Inspector (debug / layout UI)

The **Inspector** is a right-side `QDockWidget` (menu **View → Inspector**) that helps anyone see how the app interprets a PDF page: PP-DocLayout block types and bboxes, reading order, what text is sent to TTS, and optional bbox overlays on the main page.

## Design goals

- **No extra indirection** — no publish/subscribe bus. The inspector reads the same `Page` / `ReadingState` as the rest of the GUI, via the existing poll loop.
- **Optional cost** — when the dock is closed, overlays are cleared and the PDF view does not keep drawing block boxes.
- **Easy to extend** — add a new tab widget page and refresh it from `InspectorDock.update_page(...)` (or a dedicated method called from `MainWindow._on_poll`).

## Layout

| Location | Role |
|----------|------|
| [`gui/inspector/dock.py`](../src/projectwhy/gui/inspector/dock.py) | `InspectorDock`, **Layout** tab (table + overlay checkbox), **Detail** tab (block text + word list). |
| [`gui/inspector/colors.py`](../src/projectwhy/gui/inspector/colors.py) | `BLOCK_COLORS` / `rgb_for_block_type` — shared by the table and [`gui/pdf_view.py`](../src/projectwhy/gui/pdf_view.py) overlays. |
| [`gui/pdf_view.py`](../src/projectwhy/gui/pdf_view.py) | `set_show_overlays`, `set_block_overlays`, `_draw_overlays` — draws rects/labels in image space (scaled like the word highlight). |
| [`gui/app.py`](../src/projectwhy/gui/app.py) | Creates the dock, **View** menu toggle, `_on_poll` / `_refresh_page_view` updates, `open_path` → `_inspector.reset()`. |

## How to add a new panel later

1. Subclass `QWidget` with an `update_page(self, page: Page, state: ReadingState) -> None` (or whatever inputs you need).
2. In `InspectorDock.__init__`, `tabs.addTab(my_panel, "My tab")`.
3. In `InspectorDock.update_page`, call `my_panel.update_page(page, state)`.
4. If the panel must react to document replacement, reset any cached indices in `InspectorDock.reset()` (see `DetailPanel.reset_tracking`).

Examples for the future: multithreaded TTS queue depth, per-block timing, alignment dumps — each is just another tab + a few calls from the main window poll or session API.

## Overlays

Overlays are drawn **only** when the Inspector is visible **and** “Show block overlays” is checked. The active block (during playback) is emphasized on the page. Colors map to `BlockType` in `colors.py`.
