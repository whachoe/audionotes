"""Date/time recognition in transcripts via Meta's Duckling (Phase 4) -
runs as a separate HTTP service (see DUCKLING_BASE_URL); replaces the
earlier dateparser-based implementation.

Duckling's /parse endpoint takes a single language per request (no
multi-locale search like dateparser had), so this calls it once per
candidate language (see LANGUAGES below) with the same transcript and
reference time, then merges the results by the position each match starts
at in the transcript - mirroring dateparser.search()'s left-to-right match
order. The first plausible match (see _is_plausible) wins.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

LANGUAGES = ["en", "nl", "fr"]
MIN_MATCH_LENGTH = 4
MAX_YEARS_FROM_REFERENCE = 3

REQUEST_TIMEOUT_SECONDS = 5.0


def _to_local(reference_time: datetime, local_zone: ZoneInfo) -> datetime:
    """reference_time is Note.created_at, as read back from SQLite: a naive
    wall-clock value that was originally computed as UTC (see models.utcnow)
    and lost its tzinfo on the DB round-trip. Label it UTC so downstream
    conversions (epoch ms for Duckling, local zone for display) are correct.
    """
    return reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)


def _is_plausible(matched_text: str, candidate: datetime, reference_year: int) -> tuple[bool, str]:
    if len(matched_text.strip()) < MIN_MATCH_LENGTH:
        return False, f"matched text {matched_text!r} shorter than MIN_MATCH_LENGTH={MIN_MATCH_LENGTH}"
    if abs(candidate.year - reference_year) > MAX_YEARS_FROM_REFERENCE:
        return False, (
            f"candidate year {candidate.year} more than {MAX_YEARS_FROM_REFERENCE} years "
            f"from reference year {reference_year}"
        )
    return True, "ok"


def _extract_iso_value(value: dict[str, Any]) -> Optional[str]:
    """A Duckling "time" value is either {"type": "value", "value": <iso>}
    or, for a range like "this afternoon", {"type": "interval", "from": {...},
    "to": {...}} - each of which is itself a value/iso pair. Prefer "from"
    for intervals (the start of the range is the more useful anchor for
    scheduling).
    """
    if value.get("type") == "interval":
        anchor = value.get("from") or value.get("to")
        return anchor.get("value") if anchor else None
    return value.get("value")


def _query_duckling(transcript: str, lang: str, reftime_ms: int, settings: Settings) -> list[dict[str, Any]]:
    response = httpx.post(
        f"{settings.DUCKLING_BASE_URL}/parse",
        data={
            "lang": lang.upper(),
            "text": transcript,
            "dims": '["time"]',
            "tz": settings.LOCAL_TIMEZONE,
            "reftime": str(reftime_ms),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [entity for entity in response.json() if entity.get("dim") == "time"]


def find_scheduled_at(transcript: str, reference_time: datetime) -> Optional[datetime]:
    """Best-effort: the first plausible date/time Duckling finds in the
    transcript, in settings.LOCAL_TIMEZONE local time - or None if nothing
    looks like a date/time, or on any parsing error. Must never raise.
    """
    if not transcript.strip():
        return None

    settings = get_settings()
    local_zone = ZoneInfo(settings.LOCAL_TIMEZONE)
    aware_reference = _to_local(reference_time, local_zone)
    reftime_ms = int(aware_reference.timestamp() * 1000)

    logger.debug(
        "date_recognition: reference_time=%r reftime_ms=%d transcript=%r",
        reference_time,
        reftime_ms,
        transcript,
    )

    try:
        candidates: list[tuple[str, dict[str, Any]]] = []
        for lang in LANGUAGES:
            try:
                entities = _query_duckling(transcript, lang, reftime_ms, settings)
            except Exception as exc:  # noqa: BLE001 - one language failing shouldn't cost the others
                logger.debug("date_recognition: duckling request failed for lang=%s: %s", lang, exc)
                continue

            logger.debug(
                "date_recognition: duckling(lang=%s) found %d entity(ies): %r",
                lang,
                len(entities),
                [(e.get("body"), _extract_iso_value(e.get("value", {}))) for e in entities],
            )
            candidates.extend((lang, entity) for entity in entities)

        if not candidates:
            logger.debug("date_recognition: no time entities found in any language")
            return None

        # Sort by where a match starts (mirrors dateparser.search's
        # left-to-right order), and for same-start matches - which happen
        # across languages when e.g. English catches only "5 september" but
        # Dutch catches the fuller "5 september om 10 uur" - prefer the
        # longer, more complete span.
        candidates.sort(key=lambda pair: (pair[1].get("start", 0), -(pair[1].get("end", 0) - pair[1].get("start", 0))))

        for lang, entity in candidates:
            matched_text = entity.get("body", "")
            iso_value = _extract_iso_value(entity.get("value", {}))
            if iso_value is None:
                logger.debug(
                    "date_recognition: rejected match lang=%s body=%r - no usable value in response",
                    lang,
                    matched_text,
                )
                continue

            try:
                parsed = datetime.fromisoformat(iso_value).astimezone(local_zone)
            except ValueError:
                logger.debug(
                    "date_recognition: rejected match lang=%s body=%r - unparseable value %r",
                    lang,
                    matched_text,
                    iso_value,
                )
                continue

            plausible, reason = _is_plausible(matched_text, parsed, aware_reference.year)
            if plausible:
                logger.debug(
                    "date_recognition: accepted match lang=%s body=%r -> %s",
                    lang,
                    matched_text,
                    parsed.isoformat(),
                )
                return parsed

            logger.debug(
                "date_recognition: rejected match lang=%s body=%r -> %s - %s",
                lang,
                matched_text,
                parsed.isoformat(),
                reason,
            )

        logger.debug("date_recognition: no plausible match among %d candidate(s)", len(candidates))
        return None
    except Exception:  # noqa: BLE001 - date recognition must never fail the note
        logger.exception("duckling failed on transcript")
        return None
