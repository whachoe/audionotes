"""Builds the canonical markdown document for a note."""
from __future__ import annotations


def build_markdown(
    *,
    title: str,
    note_id: str,
    original_filename: str,
    transcript_text: str,
) -> str:
    safe_title = title.strip() if title and title.strip() else "Untitled note"
    audio_link_text = original_filename or "audio"
    return (
        f"# {safe_title}\n"
        f"\n"
        f"**Audio:** [{audio_link_text}](/api/notes/{note_id}/audio)\n"
        f"\n"
        f"## Transcript\n"
        f"\n"
        f"{transcript_text}\n"
    )
