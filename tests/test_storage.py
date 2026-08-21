from __future__ import annotations

from backend import storage
from backend.config import reset_settings_cache

from tests.conftest import SAMPLE_WAV


def test_ffprobe_duration_seconds_parses_real_file():
    duration = storage.ffprobe_duration_seconds(SAMPLE_WAV)
    assert duration is not None
    # The fixture is a ~0.5s clip of silence.
    assert 0.3 < duration < 1.0


def test_ffprobe_duration_seconds_returns_none_for_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.wav"
    assert storage.ffprobe_duration_seconds(missing) is None


def test_markdown_write_read_roundtrip(env_setup):
    note_id = "abc123"
    content = "# Title\n\n**Audio:** [x.wav](/api/notes/abc123/audio)\n\n## Transcript\n\nHello world.\n"

    relative_path = storage.write_markdown(note_id, content)
    assert relative_path == f"notes/{note_id}.md"

    on_disk = env_setup / "notes" / f"{note_id}.md"
    assert on_disk.exists()
    assert on_disk.read_text(encoding="utf-8") == content

    assert storage.read_markdown(note_id) == content


def test_read_markdown_returns_empty_string_when_missing(env_setup):
    assert storage.read_markdown("no-such-note") == ""


def test_audio_filename_for_preserves_extension():
    assert storage.audio_filename_for("abc", "recording.m4a") == "abc.m4a"
    assert storage.audio_filename_for("abc", None) == "abc"
    assert storage.audio_filename_for("abc", "no_extension") == "abc"
