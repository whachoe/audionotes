"""Title + date/time extraction via a local Ollama server. Non-fatal on failure.

One combined prompt asks the local LLM for both a short title and, if the
transcript clearly mentions a date/time to schedule, a date/time - reusing
the transcription-time LLM already in the pipeline rather than adding a
second model or an external date-parsing service (see docs/REQUIREMENTS.md
Phase 2.1).

Timezone handling: the model is asked to think and answer purely in local
wall-clock time (settings.LOCAL_TIMEZONE, e.g. "Europe/Brussels") - it's not
asked to reason about UTC offsets or DST at all, since LLMs are unreliable at
that arithmetic. We attach the actual IANA zone (which handles CET/CEST
automatically) ourselves after parsing, deterministically.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "You are analyzing a transcript of a spoken voice note. The current "
    "date and time, in local time ({timezone_name}), is {reference_time} - "
    "interpret any relative date/time expressions in the transcript "
    '("tomorrow", "next Tuesday at 3pm", "in two weeks", ...) relative to '
    "that, and always answer in that same local time - never convert to UTC "
    "or include a UTC offset.\n\n"
    "Respond with ONLY a single JSON object, no other text, with exactly "
    "these two keys:\n"
    '- "title": a short title for the note, at most 8 words, no quotes, no '
    "trailing period.\n"
    '- "scheduled_at": if the transcript clearly mentions or implies a '
    "specific date and/or time to schedule an event, reminder or "
    "appointment, an ISO 8601 local date/time string for it (no UTC offset, "
    "e.g. \"2026-09-05T14:00:00\"); otherwise null.\n\n"
    "Transcript:\n{transcript}\n\nJSON:"
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _fallback_title(transcript: str) -> str:
    words = transcript.strip().split()
    if not words:
        return "Untitled note"
    return " ".join(words[:10])


def _clean_title(raw: str) -> str:
    cleaned = raw.strip().strip("\"'").strip()
    if cleaned.endswith("."):
        cleaned = cleaned[:-1].strip()
    # Collapse to a single line in case the model returned more than asked.
    cleaned = cleaned.splitlines()[0].strip() if cleaned else cleaned
    return cleaned


def _to_local(reference_time: datetime, local_zone: ZoneInfo) -> datetime:
    """reference_time is Note.created_at, as read back from SQLite: a naive
    wall-clock value that was originally computed as UTC (see models.utcnow)
    and lost its tzinfo on the DB round-trip. Label it UTC, then convert to
    the configured local zone so the LLM reasons in the user's own time.
    """
    aware_utc = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(local_zone)


def _parse_local_datetime(raw: object, local_zone: ZoneInfo) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # The model was asked for a naive local value; if it included an offset
    # anyway, reinterpret it as the configured local zone rather than trust
    # its arithmetic.
    return parsed.replace(tzinfo=local_zone) if parsed.tzinfo is None else parsed.astimezone(local_zone)


def _parse_response(
    raw_response: str, fallback_title: str, local_zone: ZoneInfo
) -> Tuple[str, Optional[datetime]]:
    """Best-effort JSON parsing of the model's response. Never raises -
    any shape mismatch just falls back to a plain title with no schedule.
    """
    match = _JSON_OBJECT_RE.search(raw_response)
    if match is None:
        # The model ignored the JSON instruction and just returned text -
        # treat the whole response as a plain title, same as the old prompt.
        cleaned = _clean_title(raw_response)
        return (cleaned or fallback_title), None

    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback_title, None

    if not isinstance(obj, dict):
        return fallback_title, None

    title = _clean_title(str(obj.get("title") or "")) or fallback_title
    scheduled_at = _parse_local_datetime(obj.get("scheduled_at"), local_zone)
    return title, scheduled_at


async def generate_title_and_schedule(
    transcript: str, reference_time: datetime
) -> Tuple[str, Optional[datetime]]:
    """Ask Ollama for a short title and an optional scheduled_at datetime,
    the latter in settings.LOCAL_TIMEZONE local time.

    Falls back to the transcript's first ~10 words and no schedule on any
    error (unreachable server, bad response, timeout, ...). This must never
    raise - a failure here must never fail the note itself.
    """
    fallback = _fallback_title(transcript)
    if not transcript.strip():
        return fallback, None

    settings = get_settings()
    local_zone = ZoneInfo(settings.LOCAL_TIMEZONE)
    local_reference = _to_local(reference_time, local_zone)

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": _PROMPT_TEMPLATE.format(
            timezone_name=settings.LOCAL_TIMEZONE,
            reference_time=local_reference.strftime("%Y-%m-%d %H:%M"),
            transcript=transcript[:4000],
        ),
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "")
            return _parse_response(raw_response, fallback, local_zone)
    except Exception:  # noqa: BLE001 - summarization failures must never be fatal
        logger.exception("Ollama summarization failed; falling back to transcript excerpt")
        return fallback, None
