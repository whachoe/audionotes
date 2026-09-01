"""Title + date/time extraction via a local Ollama server. Non-fatal on failure.

One combined prompt asks the local LLM for both a short title and, if the
transcript clearly mentions a date/time to schedule, an ISO 8601 datetime -
reusing the transcription-time LLM already in the pipeline rather than adding
a second model or an external date-parsing service (see docs/REQUIREMENTS.md
Phase 2.1).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "You are analyzing a transcript of a spoken voice note. The current "
    "date and time is {reference_time} - interpret any relative date/time "
    "expressions in the transcript (\"tomorrow\", \"next Tuesday at 3pm\", "
    "\"in two weeks\", ...) relative to that.\n\n"
    "Respond with ONLY a single JSON object, no other text, with exactly "
    "these two keys:\n"
    '- "title": a short title for the note, at most 8 words, no quotes, no '
    "trailing period.\n"
    '- "scheduled_at": if the transcript clearly mentions or implies a '
    "specific date and/or time to schedule an event, reminder or "
    "appointment, an ISO 8601 datetime string for it; otherwise null.\n\n"
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


def _parse_iso_datetime(raw: object) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_response(raw_response: str, fallback_title: str) -> Tuple[str, Optional[datetime]]:
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
    scheduled_at = _parse_iso_datetime(obj.get("scheduled_at"))
    return title, scheduled_at


async def generate_title_and_schedule(
    transcript: str, reference_time: datetime
) -> Tuple[str, Optional[datetime]]:
    """Ask Ollama for a short title and an optional scheduled_at datetime.

    Falls back to the transcript's first ~10 words and no schedule on any
    error (unreachable server, bad response, timeout, ...). This must never
    raise - a failure here must never fail the note itself.
    """
    fallback = _fallback_title(transcript)
    if not transcript.strip():
        return fallback, None

    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": _PROMPT_TEMPLATE.format(
            reference_time=reference_time.isoformat(), transcript=transcript[:4000]
        ),
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "")
            return _parse_response(raw_response, fallback)
    except Exception:  # noqa: BLE001 - summarization failures must never be fatal
        logger.exception("Ollama summarization failed; falling back to transcript excerpt")
        return fallback, None
