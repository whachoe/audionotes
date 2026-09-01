from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from backend import db
from backend.models import Note, NoteStatus, ProcessingStatus

from tests.conftest import SAMPLE_WAV


def _upload(client, auth_headers, filename="sample.wav"):
    with open(SAMPLE_WAV, "rb") as f:
        return client.post(
            "/api/notes",
            files={"file": (filename, f, "audio/wav")},
            headers=auth_headers,
        )


def test_upload_creates_row_and_files(client, auth_headers, env_setup):
    response = _upload(client, auth_headers)
    assert response.status_code == 201
    body = response.json()

    assert body["processing_status"] == "queued"
    assert body["status"] == "open"
    assert body["audio_original_filename"] == "sample.wav"
    assert body["audio_url"] == f"/api/notes/{body['id']}/audio"
    assert body["duration_seconds"] is not None
    assert body["duration_seconds"] > 0

    audio_file = env_setup / "audio" / f"{body['id']}.wav"
    assert audio_file.exists()

    with db.session_scope() as session:
        note = session.get(Note, body["id"])
        assert note is not None
        assert note.audio_filename == f"{body['id']}.wav"
        assert note.processing_status == ProcessingStatus.queued


def test_list_unknown_id_404(client, auth_headers):
    response = client.get("/api/notes/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


def test_patch_status_unknown_id_404(client, auth_headers):
    response = client.patch(
        "/api/notes/does-not-exist/status", json={"status": "in_progress"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_put_transcript_unknown_id_404(client, auth_headers):
    response = client.put(
        "/api/notes/does-not-exist/transcript", json={"markdown": "# hi"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_patch_status_invalid_value_422(client, auth_headers):
    upload = _upload(client, auth_headers)
    note_id = upload.json()["id"]
    response = client.patch(
        f"/api/notes/{note_id}/status", json={"status": "not_a_real_status"}, headers=auth_headers
    )
    assert response.status_code == 422


def test_list_invalid_sort_by_422(client, auth_headers):
    response = client.get("/api/notes?sort_by=bogus", headers=auth_headers)
    assert response.status_code == 422


def test_list_invalid_order_422(client, auth_headers):
    response = client.get("/api/notes?order=bogus", headers=auth_headers)
    assert response.status_code == 422


def test_patch_status_happy_path(client, auth_headers):
    upload = _upload(client, auth_headers)
    note_id = upload.json()["id"]

    response = client.patch(
        f"/api/notes/{note_id}/status", json={"status": "in_progress"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    detail = client.get(f"/api/notes/{note_id}", headers=auth_headers)
    assert detail.json()["status"] == "in_progress"


def test_put_transcript_persists_to_file_and_db(client, auth_headers, env_setup):
    upload = _upload(client, auth_headers)
    note_id = upload.json()["id"]

    new_markdown = "# Edited title\n\n**Audio:** [sample.wav](/api/notes/%s/audio)\n\n## Transcript\n\nHand-edited content.\n" % note_id
    response = client.put(
        f"/api/notes/{note_id}/transcript", json={"markdown": new_markdown}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["transcript_markdown"] == new_markdown

    detail = client.get(f"/api/notes/{note_id}", headers=auth_headers)
    assert detail.json()["transcript_markdown"] == new_markdown

    md_file = env_setup / "notes" / f"{note_id}.md"
    assert md_file.read_text(encoding="utf-8") == new_markdown

    with db.session_scope() as session:
        note = session.get(Note, note_id)
        assert note.transcript_path == f"notes/{note_id}.md"


def _seed_note(session: Session, **overrides) -> Note:
    defaults = dict(
        audio_filename="x.wav",
        audio_original_filename="x.wav",
        audio_mime_type="audio/wav",
        status=NoteStatus.open,
        processing_status=ProcessingStatus.done,
        duration_seconds=1.0,
    )
    defaults.update(overrides)
    note = Note(**defaults)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def test_list_sort_by_duration_seconds(client, auth_headers):
    now = datetime.now(timezone.utc)
    with db.session_scope() as session:
        _seed_note(session, duration_seconds=5.0, created_at=now, title="five")
        _seed_note(session, duration_seconds=1.0, created_at=now, title="one")
        _seed_note(session, duration_seconds=3.0, created_at=now, title="three")

    response = client.get("/api/notes?sort_by=duration_seconds&order=asc", headers=auth_headers)
    assert response.status_code == 200
    durations = [item["duration_seconds"] for item in response.json()]
    assert durations == [1.0, 3.0, 5.0]

    response_desc = client.get("/api/notes?sort_by=duration_seconds&order=desc", headers=auth_headers)
    durations_desc = [item["duration_seconds"] for item in response_desc.json()]
    assert durations_desc == [5.0, 3.0, 1.0]


def test_list_sort_by_created_at(client, auth_headers):
    base = datetime.now(timezone.utc)
    with db.session_scope() as session:
        _seed_note(session, created_at=base, title="oldest")
        _seed_note(session, created_at=base + timedelta(minutes=5), title="middle")
        _seed_note(session, created_at=base + timedelta(minutes=10), title="newest")

    response = client.get("/api/notes?sort_by=created_at&order=desc", headers=auth_headers)
    titles = [item["title"] for item in response.json()]
    assert titles == ["newest", "middle", "oldest"]

    response_asc = client.get("/api/notes?sort_by=created_at&order=asc", headers=auth_headers)
    titles_asc = [item["title"] for item in response_asc.json()]
    assert titles_asc == ["oldest", "middle", "newest"]


def test_list_sort_by_status(client, auth_headers):
    now = datetime.now(timezone.utc)
    with db.session_scope() as session:
        _seed_note(session, created_at=now, status=NoteStatus.todo, title="a")
        _seed_note(session, created_at=now, status=NoteStatus.closed, title="b")
        _seed_note(session, created_at=now, status=NoteStatus.open, title="c")

    response = client.get("/api/notes?sort_by=status&order=asc", headers=auth_headers)
    statuses = [item["status"] for item in response.json()]
    assert statuses == sorted(statuses)


def test_list_default_returns_metadata_only(client, auth_headers):
    _upload(client, auth_headers)
    response = client.get("/api/notes", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert set(item.keys()) == {
        "id",
        "created_at",
        "updated_at",
        "title",
        "status",
        "processing_status",
        "duration_seconds",
        "audio_url",
        "scheduled_at",
    }


def test_get_audio_streams_bytes(client, auth_headers, sample_wav_bytes):
    upload = _upload(client, auth_headers)
    note_id = upload.json()["id"]

    response = client.get(f"/api/notes/{note_id}/audio", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == sample_wav_bytes
    assert response.headers["accept-ranges"] == "bytes"


def test_get_audio_supports_range(client, auth_headers, sample_wav_bytes):
    upload = _upload(client, auth_headers)
    note_id = upload.json()["id"]

    headers = dict(auth_headers)
    headers["Range"] = "bytes=0-9"
    response = client.get(f"/api/notes/{note_id}/audio", headers=headers)
    assert response.status_code == 206
    assert response.content == sample_wav_bytes[0:10]
    assert response.headers["content-range"] == f"bytes 0-9/{len(sample_wav_bytes)}"
