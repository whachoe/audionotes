"""Filesystem layout helpers: audio files, markdown files, ffprobe duration."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import BinaryIO, Optional

from .config import get_settings

logger = logging.getLogger(__name__)


def data_dir() -> Path:
    return Path(get_settings().DATA_DIR)


def audio_dir() -> Path:
    d = data_dir() / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def notes_dir() -> Path:
    d = data_dir() / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_path(note_id: str, audio_filename: str) -> Path:
    return audio_dir() / audio_filename


def markdown_path(note_id: str) -> Path:
    return notes_dir() / f"{note_id}.md"


def audio_filename_for(note_id: str, original_filename: Optional[str]) -> str:
    ext = ""
    if original_filename:
        ext = Path(original_filename).suffix
    return f"{note_id}{ext}"


def save_upload_to_disk(note_id: str, original_filename: Optional[str], file_obj: BinaryIO) -> str:
    """Save an uploaded file-like object to disk under DATA_DIR/audio.

    Returns the stored filename (relative, e.g. "<id>.m4a").
    """
    filename = audio_filename_for(note_id, original_filename)
    dest = audio_path(note_id, filename)
    with open(dest, "wb") as out:
        shutil.copyfileobj(file_obj, out)
    return filename


def ffprobe_duration_seconds(path: os.PathLike | str) -> Optional[float]:
    """Run ffprobe to get the duration of an audio file, in seconds.

    Returns None (and logs) if ffprobe is unavailable or the file can't be probed,
    rather than raising - a bad/missing duration should never block an upload.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
        duration = data.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except Exception:  # noqa: BLE001
        logger.exception("ffprobe failed for %s", path)
        return None


def write_markdown(note_id: str, content: str) -> str:
    """Write markdown content verbatim to DATA_DIR/notes/<id>.md.

    Returns the path stored (relative to DATA_DIR, for the transcript_path column).
    """
    path = markdown_path(note_id)
    path.write_text(content, encoding="utf-8")
    return str(Path("notes") / f"{note_id}.md")


def read_markdown(note_id: str) -> str:
    """Read markdown content for a note. Returns "" if no transcript exists yet."""
    path = markdown_path(note_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
