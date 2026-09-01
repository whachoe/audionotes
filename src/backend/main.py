"""FastAPI application factory and lifespan-managed background worker."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .auth import RequireLoginRedirect
from .config import get_settings
from .routers import google_auth, health, notes, web
from .worker import recover_stuck_jobs, run_worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent


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
    app = FastAPI(title="Copywaste Notes", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(notes.router, prefix="/api")
    app.include_router(google_auth.router, prefix="/api")
    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=str(_BACKEND_DIR / "static")), name="static")

    @app.exception_handler(RequireLoginRedirect)
    async def _redirect_to_login(request: Request, exc: RequireLoginRedirect) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=302)

    return app


app = create_app()
