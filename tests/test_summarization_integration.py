"""Integration test for real Ollama-backed title generation. Requires a
reachable Ollama server (OLLAMA_BASE_URL) - skipped automatically otherwise,
see conftest.ollama_reachable(). See deploy/docker-compose.test.yml to spin
one up locally.

conftest.patch_services replaces summarization.generate_title with a fake
for every other test in the suite (so the rest of the suite stays fast and
deterministic); this file grabs the real function before that patch applies
each test, by capturing it at import time below.
"""
from __future__ import annotations

import pytest

from backend.services import summarization
from backend.services.summarization import _fallback_title
from tests.conftest import ollama_reachable

pytestmark = pytest.mark.skipif(not ollama_reachable(), reason="Ollama server not reachable")

_real_generate_title = summarization.generate_title

TRANSCRIPT = (
    "Remember to call the dentist tomorrow at 2pm to reschedule the cleaning "
    "appointment, and pick up the dry cleaning on the way back."
)


@pytest.mark.asyncio
async def test_generate_title_returns_a_real_summarized_title():
    title = await _real_generate_title(TRANSCRIPT)

    assert title != _fallback_title(TRANSCRIPT), (
        "generate_title() fell back to the naive first-10-words title instead of a real "
        "model response - check that OLLAMA_MODEL is actually pulled on the Ollama server "
        "(`docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml "
        "exec ollama ollama pull <model>`)"
    )
    # The prompt asks for at most 8 words; a little slack for model variance.
    assert len(title.split()) <= 12
