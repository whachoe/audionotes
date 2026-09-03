"""Title generation via a local Ollama server. Non-fatal on failure.

Date/time recognition used to be folded into this same LLM call (Phase 2's
original implementation); it now runs separately via the `dateparser`
library instead - see services/date_recognition.py - so this module is back
to doing exactly one thing.
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "Summarize the following voice note transcript as a short title, "
    "at most 8 words. Respond with only the title text: no quotes, "
    "no trailing period, no extra commentary.\n\n"
    "Transcript:\n{transcript}\n\nTitle:"
)


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


async def generate_title(transcript: str) -> str:
    """Ask Ollama for a short title. Falls back to the transcript's first
    ~10 words on any error (unreachable server, bad response, timeout, ...).
    This must never raise.
    """
    fallback = _fallback_title(transcript)
    if not transcript.strip():
        return fallback

    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": _PROMPT_TEMPLATE.format(transcript=transcript[:4000]),
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_title = data.get("response", "")
            cleaned = _clean_title(raw_title)
            return cleaned or fallback
    except Exception:  # noqa: BLE001 - summarization failures must never be fatal
        logger.exception("Ollama summarization failed; falling back to transcript excerpt")
        return fallback
