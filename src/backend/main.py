"""FastAPI application factory and lifespan-managed background worker."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .config import get_settings
from .routers import health, notes
from .worker import recover_stuck_jobs, run_worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    db.configure_engine(settings.DATA_DIR)
    db.init_db()

    with db.session_scope() as session:
        reset_count = recover_stuck_jobs(session)
        if reset_count:
            logger.info("Reset %d stuck job(s) back to queued on startup", reset_count)

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        run_worker_loop(db.session_scope, settings.POLL_INTERVAL_SECONDS, stop_event)
    )

    try:
        yield
    finally:
        stop_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        db.reset_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="cjpa's Notes", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(notes.router, prefix="/api")
    return app


app = create_app()
