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


def _is_plausible(matched_text: str, candidate: datetime, reference_year: int) -> tuple[bool, str]:
    if len(matched_text.strip()) < MIN_MATCH_LENGTH:
        return False, f"matched text {matched_text!r} shorter than MIN_MATCH_LENGTH={MIN_MATCH_LENGTH}"
    if abs(candidate.year - reference_year) > MAX_YEARS_FROM_REFERENCE:
        return False, (
            f"candidate year {candidate.year} more than {MAX_YEARS_FROM_REFERENCE} years "
            f"from reference year {reference_year}"
        )
    return True, "ok"


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

    logger.debug(
        "date_recognition: reference_time=%r local_reference=%r transcript=%r",
        reference_time,
        local_reference,
        transcript,
    )

    try:
        matches = dateparser.search.search_dates(transcript, languages=LANGUAGES, settings=parser_settings)
        if not matches:
            logger.debug("date_recognition: search_dates found no matches")
            return None

        logger.debug(
            "date_recognition: search_dates found %d match(es): %r",
            len(matches),
            [(text, dt.isoformat()) for text, dt in matches],
        )

        for matched_text, search_dt in matches:
            # Re-parse the matched span on its own rather than trusting the
            # datetime search_dates() already attached to it - see module
            # docstring point 1.
            reparsed = dateparser.parse(matched_text, languages=LANGUAGES, settings=parser_settings)
            if reparsed is None:
                logger.debug(
                    "date_recognition: rejected match %r - re-parse returned None (search_dates had given %s)",
                    matched_text,
                    search_dt.isoformat(),
                )
                continue

            plausible, reason = _is_plausible(matched_text, reparsed, local_reference.year)
            if plausible:
                logger.debug(
                    "date_recognition: accepted match %r -> %s (search_dates had given %s)",
                    matched_text,
                    reparsed.isoformat(),
                    search_dt.isoformat(),
                )
                return reparsed

            logger.debug(
                "date_recognition: rejected match %r -> %s - %s",
                matched_text,
                reparsed.isoformat(),
                reason,
            )

        logger.debug("date_recognition: no plausible match among %d candidate(s)", len(matches))
        return None
    except Exception:  # noqa: BLE001 - date recognition must never fail the note
        logger.exception("dateparser failed on transcript")
        return None
