"""Confirms the additive-column migration in db.py doesn't break (or lose
data from) a database created before scheduled_at/user_id existed - the
exact situation the live production server is in across Phase 2 and Phase 3.
"""
from __future__ import annotations

from sqlmodel import Session, SQLModel, text

from backend import db
from backend.models import GoogleCredential, User


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


def test_old_shaped_googlecredential_table_is_dropped_and_recreated(tmp_path):
    """googlecredential moved from a Phase 2 singleton (`id` primary key) to
    a Phase 3 per-user row (`user_id` primary key) - a real schema change
    ADD COLUMN can't fix. This is exactly what caused a live 500 on
    /google/auth/callback against a server still holding the old table.
    """
    data_dir = tmp_path / "data"
    engine = db.create_db_engine(str(data_dir))

    with engine.connect() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE googlecredential (
                id INTEGER PRIMARY KEY,
                access_token VARCHAR,
                refresh_token VARCHAR,
                pending_state VARCHAR,
                updated_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO googlecredential (id, access_token, refresh_token) "
            "VALUES (1, 'old-access-token', 'old-refresh-token')"
        )
        conn.commit()

    db._drop_incompatible_tables(engine)
    SQLModel.metadata.create_all(engine)
    db._add_missing_columns(engine)

    with Session(engine) as session:
        columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(googlecredential)")).all()  # type: ignore[arg-type]
        }
        assert "user_id" in columns
        assert "id" not in columns  # old singleton primary key is gone

        # The new schema actually works: a real insert/query round-trips.
        user = User(google_sub="sub-1", email="test@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)

        cred = GoogleCredential(user_id=user.id, access_token="new-token", refresh_token="new-refresh")
        session.add(cred)
        session.commit()

        fetched = session.get(GoogleCredential, user.id)
        assert fetched is not None
        assert fetched.refresh_token == "new-refresh"

    # Running it again (e.g. a second server restart, now on the new schema) must be a no-op.
    db._drop_incompatible_tables(engine)
    with Session(engine) as session:
        assert session.get(GoogleCredential, user.id) is not None
