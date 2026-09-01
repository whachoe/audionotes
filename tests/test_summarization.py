from __future__ import annotations

from datetime import datetime, timezone

from backend.services.summarization import _parse_response


def test_parses_title_and_schedule_from_json():
    raw = '{"title": "Dentist appointment", "scheduled_at": "2026-09-05T14:00:00+00:00"}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == "Dentist appointment"
    assert scheduled_at == datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)


def test_null_schedule_is_none():
    raw = '{"title": "Grocery list", "scheduled_at": null}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == "Grocery list"
    assert scheduled_at is None


def test_json_wrapped_in_commentary_is_still_parsed():
    raw = 'Sure, here is the JSON:\n{"title": "Call Marcus", "scheduled_at": null}\nHope that helps!'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == "Call Marcus"
    assert scheduled_at is None


def test_invalid_datetime_string_falls_back_to_none():
    raw = '{"title": "Some note", "scheduled_at": "not a real date"}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == "Some note"
    assert scheduled_at is None


def test_non_json_response_falls_back_to_plain_title_text():
    raw = "Just a plain title with no JSON at all"
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == raw
    assert scheduled_at is None


def test_malformed_json_falls_back_to_fallback_title():
    # Braces present (so the JSON-object regex matches) but invalid JSON
    # (trailing comma) - must fall back rather than raise.
    raw = '{"title": "broken",}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback")
    assert title == "fallback"
    assert scheduled_at is None


def test_empty_response_falls_back_to_fallback_title():
    title, scheduled_at = _parse_response("", fallback_title="fallback")
    assert title == "fallback"
    assert scheduled_at is None
