"""Confirms the additive-column migration in db.py doesn't break (or lose
data from) a database created before scheduled_at/user_id existed - the
exact situation the live production server is in across Phase 2 and Phase 3.
"""
from __future__ import annotations

from sqlmodel import Session, text

from backend import db


def test_missing_columns_are_added_without_losing_data(tmp_path):
    data_dir = tmp_path / "data"
    engine = db.create_db_engine(str(data_dir))

    # Simulate the pre-Phase-2 schema: a `note` table with neither
    # scheduled_at (Phase 2) nor user_id (Phase 3), and one real row in it.
    with engine.connect() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE note (
                id VARCHAR PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                title VARCHAR,
                status VARCHAR,
                processing_status VARCHAR,
                processing_error VARCHAR,
                duration_seconds FLOAT,
                audio_filename VARCHAR NOT NULL,
                audio_original_filename VARCHAR,
                audio_mime_type VARCHAR,
                transcript_path VARCHAR
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO note (id, audio_filename, status, processing_status) "
            "VALUES ('pre-existing-note', 'old.wav', 'open', 'done')"
        )
        conn.commit()

    db._add_missing_columns(engine)

    with Session(engine) as session:
        columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(note)")).all()  # type: ignore[arg-type]
        }
        assert "scheduled_at" in columns
        assert "user_id" in columns

        row = session.exec(
            text("SELECT id, audio_filename, scheduled_at, user_id FROM note WHERE id = 'pre-existing-note'")
        ).first()
        assert row is not None
        assert row[0] == "pre-existing-note"
        assert row[1] == "old.wav"
        assert row[2] is None  # new column, no backfill - existing notes just have no schedule
        assert row[3] is None  # ownerless until the first Phase 3 sign-in claims it

    # Running it again (e.g. a second server restart) must be a no-op, not an error.
    db._add_missing_columns(engine)
