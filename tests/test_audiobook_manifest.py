"""Audiobook manifest resume: index-addressed chapter rows."""

from projectwhy.core.audiobook import _hydrate_chapter_rows


def test_hydrate_restores_slots_by_list_index() -> None:
    old = {
        "version": 1,
        "engine_id": "kokoro",
        "voice": "af_heart",
        "speed": 1.0,
        "chapters": [
            {"index": 0, "wav": "chapter_0000.wav", "content_hash": "aa", "duration_sec": 1.0, "title": "A"},
            {"index": 1, "wav": "chapter_0001.wav", "content_hash": "bb", "duration_sec": 2.0, "title": "B"},
        ],
    }
    rows = _hydrate_chapter_rows(old, 4, "kokoro", "af_heart", 1.0)
    assert rows[0] is not None and rows[0]["content_hash"] == "aa"
    assert rows[1] is not None and rows[1]["content_hash"] == "bb"
    assert rows[2] is None and rows[3] is None


def test_hydrate_uses_index_field_when_entries_out_of_order() -> None:
    old = {
        "version": 1,
        "engine_id": "kokoro",
        "voice": "af_heart",
        "speed": 1.0,
        "chapters": [
            {"index": 2, "wav": "chapter_0002.wav", "content_hash": "cc", "duration_sec": 3.0, "title": "C"},
            {"index": 0, "wav": "chapter_0000.wav", "content_hash": "aa", "duration_sec": 1.0, "title": "A"},
        ],
    }
    rows = _hydrate_chapter_rows(old, 3, "kokoro", "af_heart", 1.0)
    assert rows[0]["content_hash"] == "aa"
    assert rows[1] is None
    assert rows[2]["content_hash"] == "cc"


def test_hydrate_rejects_wrong_engine() -> None:
    old = {
        "version": 1,
        "engine_id": "openai",
        "voice": "x",
        "speed": 1.0,
        "chapters": [{"index": 0, "content_hash": "z", "wav": "chapter_0000.wav", "duration_sec": 1.0, "title": ""}],
    }
    rows = _hydrate_chapter_rows(old, 1, "kokoro", "af_heart", 1.0)
    assert rows[0] is None


def test_hydrate_json_null_slots() -> None:
    """Simulates partial run: chapter 0 done, chapter 1 pending."""
    old = {
        "version": 1,
        "engine_id": "kokoro",
        "voice": "af_heart",
        "speed": 1.0,
        "chapters": [
            {"index": 0, "wav": "chapter_0000.wav", "content_hash": "aa", "duration_sec": 1.0, "title": "A"},
            None,
            {"index": 2, "wav": "chapter_0002.wav", "content_hash": "cc", "duration_sec": 3.0, "title": "C"},
        ],
    }
    rows = _hydrate_chapter_rows(old, 3, "kokoro", "af_heart", 1.0)
    assert rows[0] is not None
    assert rows[1] is None
    assert rows[2] is not None
