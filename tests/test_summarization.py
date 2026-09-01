from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.services.summarization import _parse_response, _to_local

BRUSSELS = ZoneInfo("Europe/Brussels")


def test_to_local_treats_naive_reference_time_as_utc():
    # Note.created_at comes back from SQLite as naive but was originally
    # computed as UTC wall-clock (models.utcnow) - 12:00 UTC in September is
    # 14:00 in Brussels (CEST, UTC+2).
    naive_utc_created_at = datetime(2026, 9, 5, 12, 0)
    local = _to_local(naive_utc_created_at, BRUSSELS)
    assert local == datetime(2026, 9, 5, 14, 0, tzinfo=BRUSSELS)


def test_to_local_also_handles_an_already_aware_reference_time():
    aware = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    local = _to_local(aware, BRUSSELS)
    assert local == datetime(2026, 9, 5, 14, 0, tzinfo=BRUSSELS)


def test_parses_title_and_schedule_from_json():
    raw = '{"title": "Dentist appointment", "scheduled_at": "2026-09-05T14:00:00"}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "Dentist appointment"
    # September is CEST (UTC+2) in Europe/Brussels.
    assert scheduled_at == datetime(2026, 9, 5, 14, 0, tzinfo=BRUSSELS)
    assert scheduled_at.utcoffset().total_seconds() == 2 * 3600


def test_winter_date_gets_cet_not_cest():
    raw = '{"title": "New Year call", "scheduled_at": "2026-01-05T10:00:00"}'
    _, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    # January is CET (UTC+1) in Europe/Brussels - not a fixed CEST offset.
    assert scheduled_at.utcoffset().total_seconds() == 1 * 3600


def test_model_offset_is_overridden_by_the_configured_zone():
    # If the model ignores the "no UTC offset" instruction, we reinterpret
    # the wall-clock numbers as local time rather than trust its offset math.
    raw = '{"title": "Call", "scheduled_at": "2026-09-05T14:00:00+05:00"}'
    _, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert scheduled_at.tzinfo == BRUSSELS


def test_null_schedule_is_none():
    raw = '{"title": "Grocery list", "scheduled_at": null}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "Grocery list"
    assert scheduled_at is None


def test_json_wrapped_in_commentary_is_still_parsed():
    raw = 'Sure, here is the JSON:\n{"title": "Call Marcus", "scheduled_at": null}\nHope that helps!'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "Call Marcus"
    assert scheduled_at is None


def test_invalid_datetime_string_falls_back_to_none():
    raw = '{"title": "Some note", "scheduled_at": "not a real date"}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "Some note"
    assert scheduled_at is None


def test_non_json_response_falls_back_to_plain_title_text():
    raw = "Just a plain title with no JSON at all"
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == raw
    assert scheduled_at is None


def test_malformed_json_falls_back_to_fallback_title():
    # Braces present (so the JSON-object regex matches) but invalid JSON
    # (trailing comma) - must fall back rather than raise.
    raw = '{"title": "broken",}'
    title, scheduled_at = _parse_response(raw, fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "fallback"
    assert scheduled_at is None


def test_empty_response_falls_back_to_fallback_title():
    title, scheduled_at = _parse_response("", fallback_title="fallback", local_zone=BRUSSELS)
    assert title == "fallback"
    assert scheduled_at is None
