from __future__ import annotations

from backend.services.summarization import _clean_title, _fallback_title


def test_fallback_title_takes_first_ten_words():
    transcript = " ".join(f"word{i}" for i in range(20))
    assert _fallback_title(transcript) == " ".join(f"word{i}" for i in range(10))


def test_fallback_title_of_empty_transcript_is_untitled():
    assert _fallback_title("   ") == "Untitled note"


def test_clean_title_strips_quotes_and_trailing_period():
    assert _clean_title('"Grocery list for the week."') == "Grocery list for the week"


def test_clean_title_collapses_to_first_line():
    raw = "Call the dentist\nSome extra commentary the model wasn't asked for"
    assert _clean_title(raw) == "Call the dentist"


def test_clean_title_of_empty_string_is_empty():
    assert _clean_title("") == ""
