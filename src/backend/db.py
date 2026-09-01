"""SQLite engine (WAL mode) and session management."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

_engine: Optional[Engine] = None


def db_path_for(data_dir: str) -> str:
    return os.path.join(data_dir, "db.sqlite3")


def create_db_engine(data_dir: str) -> Engine:
    """Create a new SQLite engine rooted at data_dir, with WAL mode enabled."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    db_path = db_path_for(data_dir)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def configure_engine(data_dir: str) -> Engine:
    """(Re)configure the module-level engine. Used at app startup and by tests."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = create_db_engine(data_dir)
    return _engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        from .config import get_settings

        _engine = create_db_engine(get_settings().DATA_DIR)
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def _drop_incompatible_tables(engine: Engine) -> None:
    """create_all() only creates *missing* tables - it never reshapes an
    existing one. google_credential moved from a Phase 2 singleton (`id`
    primary key) to a Phase 3 per-user row (`user_id` primary key, a
    different column set entirely) - not something an ADD COLUMN can fix.
    Drop the old-shaped table so create_all() below recreates it correctly;
    any previously-linked Google account just needs to sign in again via the
    new combined flow, which it must do anyway now that Calendar linking is
    tied to a real multi-user account rather than a single fixed row.
    """
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        # SQLModel's default table name is the lowercased class name with no
        # separators (GoogleCredential -> "googlecredential") - not the
        # snake_case you'd get from a naming convention, so this must match
        # GoogleCredential.__tablename__ exactly, not a guessed spelling.
        if "googlecredential" in tables:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(googlecredential)").fetchall()}
            if "user_id" not in columns:
                conn.exec_driver_sql("DROP TABLE googlecredential")
                conn.commit()


def _add_missing_columns(engine: Engine) -> None:
    """SQLModel.metadata.create_all only creates missing *tables* - it never
    alters an already-existing one. This adds any columns a model has grown
    since a table was first created, so upgrading in place (a live server
    with real notes already in it) doesn't break on missing columns.
    """
    # (table_name, column_name, column_type_for_ALTER_TABLE)
    additive_columns = [
        ("note", "scheduled_at", "TIMESTAMP"),
        ("note", "user_id", "VARCHAR"),
    ]
    with engine.connect() as conn:
        for table_name, column_name, column_type in additive_columns:
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            }
            if column_name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        conn.commit()


def init_db() -> None:
    engine = get_engine()
    _drop_incompatible_tables(engine)
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def session_scope() -> Session:
    """Return a brand new Session bound to the current engine (for the worker)."""
    return Session(get_engine())
