"""Date/time recognition in transcripts via the `dateparser` library
(Phase 2) - runs entirely locally, no LLM call involved.

Two quirks of dateparser.search.search_dates() showed up in testing against
real transcript-shaped sentences, and both are guarded against below:

1. search_dates() finds a matching span AND resolves it to a datetime in one
   step, and that resolution can be wrong even when the span it found is
   fine - e.g. "December 5th at 10am" resolved via search_dates() alone came
   back as the year 2110. Re-parsing the exact matched text with a fresh
   dateparser.parse() call (same settings) gives the correct year. This is
   also what lets a match be individually rejected without discarding the
   whole result if a later match is fine.
2. search_dates() sometimes truncates its own match short (e.g. cutting
   "10 in the morning" down to "10 in the"), which re-parses to nonsense
   regardless. A short, low-information match (below MIN_MATCH_LENGTH) is
   also how plain words like "We" get misread as an abbreviated weekday.
   Both are caught by _is_plausible() below - the match-length floor for the
   second, the year sanity bound for both (a truncated fragment tends to
   produce a wildly wrong year, same symptom as issue 1).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import dateparser
import dateparser.search

from ..config import get_settings

logger = logging.getLogger(__name__)

# The languages a Belgian user is most likely to actually speak into the
# app. Restricting this list (rather than leaving it unset, which makes
# dateparser try every supported locale) keeps search_dates() fast.
LANGUAGES = ["en", "nl", "fr"]

MIN_MATCH_LENGTH = 4
MAX_YEARS_FROM_REFERENCE = 3


def _to_local(reference_time: datetime, local_zone: ZoneInfo) -> datetime:
    """reference_time is Note.created_at, as read back from SQLite: a naive
    wall-clock value that was originally computed as UTC (see models.utcnow)
    and lost its tzinfo on the DB round-trip. Label it UTC, then convert to
    the configured local zone so "tomorrow"/"next Tuesday" etc. resolve
    relative to the user's own time, not the server's.
    """
    aware_utc = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(local_zone)


def _is_plausible(matched_text: str, candidate: datetime, reference_year: int) -> bool:
    if len(matched_text.strip()) < MIN_MATCH_LENGTH:
        return False
    if abs(candidate.year - reference_year) > MAX_YEARS_FROM_REFERENCE:
        return False
    return True


def find_scheduled_at(transcript: str, reference_time: datetime) -> Optional[datetime]:
    """Best-effort: the first plausible date/time dateparser finds in the
    transcript, in settings.LOCAL_TIMEZONE local time - or None if nothing
    looks like a date/time, or on any parsing error. Must never raise.
    """
    if not transcript.strip():
        return None

    settings = get_settings()
    local_zone = ZoneInfo(settings.LOCAL_TIMEZONE)
    local_reference = _to_local(reference_time, local_zone).replace(tzinfo=None)

    parser_settings = {
        "RELATIVE_BASE": local_reference,
        "TIMEZONE": settings.LOCAL_TIMEZONE,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
    }

    try:
        matches = dateparser.search.search_dates(transcript, languages=LANGUAGES, settings=parser_settings)
        if not matches:
            return None

        for matched_text, _ in matches:
            # Re-parse the matched span on its own rather than trusting the
            # datetime search_dates() already attached to it - see module
            # docstring point 1.
            reparsed = dateparser.parse(matched_text, languages=LANGUAGES, settings=parser_settings)
            if reparsed is not None and _is_plausible(matched_text, reparsed, local_reference.year):
                return reparsed

        return None
    except Exception:  # noqa: BLE001 - date recognition must never fail the note
        logger.exception("dateparser failed on transcript")
        return None
