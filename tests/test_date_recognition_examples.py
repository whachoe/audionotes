"""Diagnostic harness for dateparser mismatches found in real transcripts.

Add each mismatch you find to EXAMPLES below (transcript, reference time,
and what you expected it to resolve to - or None if it shouldn't match at
all), then run:

    pytest tests/test_date_recognition_examples.py -v

A failing case prints every candidate dateparser.search found, whether it
was accepted or rejected, and why (via the DEBUG logging in
date_recognition.py) - so you can see exactly where a mismatch happens
instead of just "wrong result".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

import pytest

from backend.services.date_recognition import find_scheduled_at

REFERENCE = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)  # a Thursday


@dataclass
class Example:
    id: str
    transcript: str
    expected: Optional[Tuple[int, int, int, int, int]]  # (year, month, day, hour, minute) or None
    reference: datetime = REFERENCE


EXAMPLES = [
    Example(
        id="dentist-tomorrow",
        transcript="Remember to call the dentist tomorrow at 2pm",
        expected=(2026, 9, 4, 14, 0),
    ),
    Example(
        id="doctor-appointment",
        transcript="volgende woensdag om 9 uur dokters bezoek plannen.",
        expected=(2026, 9, 9, 9, 0),
    ),
    Example(
        id="etentje",
        transcript="Over de morgen aan 13 uur eetendje.",
        expected=(2026, 9, 6, 13, 0),
    ),
    Example(
        id="logs-nakijken",
        transcript="5 september om 10 uur lochsnaar kijken.",
        expected=(2026, 9, 5, 10, 0),
    ),
    # Paste real mismatches here as you find them, e.g.:
    # Example(
    #     id="mismatch-1",
    #     transcript="<exact transcript text>",
    #     expected=(2026, 10, 12, 9, 0),  # what it SHOULD resolve to, or None
    # ),
]


@pytest.mark.parametrize("example", EXAMPLES, ids=[e.id for e in EXAMPLES])
def test_example(example: Example, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="backend.services.date_recognition")

    scheduled = find_scheduled_at(example.transcript, example.reference)
    actual = (
        None
        if scheduled is None
        else (scheduled.year, scheduled.month, scheduled.day, scheduled.hour, scheduled.minute)
    )

    if actual != example.expected:
        trace = "\n".join(record.message for record in caplog.records)
        pytest.fail(
            f"\ntranscript: {example.transcript!r}\n"
            f"expected:   {example.expected}\n"
            f"got:        {actual}\n"
            f"--- dateparser trace ---\n{trace}\n"
        )
