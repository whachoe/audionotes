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


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def session_scope() -> Session:
    """Return a brand new Session bound to the current engine (for the worker)."""
    return Session(get_engine())
