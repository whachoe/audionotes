"""Regression tests for Duckling-based date/time recognition (Phase 4).
Requires a reachable Duckling server (DUCKLING_BASE_URL) - skipped
automatically otherwise, see conftest.duckling_reachable().

Some of these lock in behavior that used to be broken under the earlier
dateparser-based implementation: a short, low-information match like the
bare word "We" shouldn't be misread as a date, and a wildly-wrong year
should never come out the other end.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.date_recognition import find_scheduled_at
from tests.conftest import duckling_reachable

pytestmark = pytest.mark.skipif(not duckling_reachable(), reason="Duckling server not reachable")

REFERENCE = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)  # a Thursday
REFERENCE_YEAR = 2026


def test_finds_a_relative_date_and_time():
    scheduled = find_scheduled_at("Remember to call the dentist tomorrow at 2pm", REFERENCE)
    assert scheduled is not None
    assert (scheduled.year, scheduled.month, scheduled.day) == (2026, 9, 4)
    assert scheduled.hour == 14


def test_finds_a_weekday_and_time():
    scheduled = find_scheduled_at("Let us meet next Tuesday at 3pm for the review", REFERENCE)
    assert scheduled is not None
    assert scheduled.weekday() == 1  # Tuesday
    assert scheduled.hour == 15


def test_returns_none_when_no_date_is_mentioned():
    assert find_scheduled_at("Just some random notes about groceries and cooking", REFERENCE) is None


def test_returns_none_for_empty_transcript():
    assert find_scheduled_at("", REFERENCE) is None


def test_result_is_in_local_timezone_with_correct_dst_offset():
    # September is CEST (UTC+2) in Europe/Brussels.
    scheduled = find_scheduled_at("let's talk tomorrow at 9am", REFERENCE)
    assert scheduled is not None
    assert scheduled.utcoffset().total_seconds() == 2 * 3600


def test_does_not_mistake_a_short_word_for_a_weekday():
    """Regression: "We should schedule the demo..." - dateparser's search
    matched the bare word "We" as if it were an abbreviated weekday. The
    minimum-match-length filter must reject it and fall through to the real
    date later in the sentence, not return the bogus one.
    """
    scheduled = find_scheduled_at(
        "We should schedule the demo for December 5th at 10am", REFERENCE
    )
    assert scheduled is not None
    assert (scheduled.year, scheduled.month, scheduled.day) == (REFERENCE_YEAR, 12, 5)
    assert scheduled.hour == 10


def test_does_not_produce_a_wildly_wrong_year():
    """Regression: search_dates() resolved "December 5th at 10 in the"
    (its own truncated match, missing "morning") to the year 2110. The
    year-sanity bound must reject that and return None rather than an
    obviously-broken date decades in the future.
    """
    scheduled = find_scheduled_at(
        "Let's schedule the demo for December 5th at 10 in the morning", REFERENCE
    )
    if scheduled is not None:
        assert abs(scheduled.year - REFERENCE_YEAR) <= 3


def test_picks_the_first_plausible_date_when_multiple_are_mentioned():
    scheduled = find_scheduled_at(
        "Call Marcus on Friday, and the report is due next Monday", REFERENCE
    )
    assert scheduled is not None
    assert scheduled.weekday() == 4  # Friday - mentioned first
