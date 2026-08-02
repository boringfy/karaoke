from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import jobs, lyrics, songs
from .config import get_settings
from .db import session as db_session
from .pipeline.worker import PipelineWorker

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    db_session.init_engine(settings.db_path)
    await db_session.create_all()
    worker = PipelineWorker(db_session.session_factory())
    await worker.start()
    app.state.worker = worker
    log.info("karaoke-server ready; data dir: %s", settings.data_dir)
    try:
        yield
    finally:
        await worker.stop()
        await db_session.dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="karaoke-server",
        version=__version__,
        description=(
            "Local-first karaoke server: create a song, upload audio you own, "
            "get auto-fetched lyrics force-aligned into word-level karaoke "
            "subtitles (with furigana for Japanese), and optionally generate "
            "an instrumental by removing vocals."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    prefix = "/api/v1"
    app.include_router(songs.router, prefix=prefix)
    app.include_router(lyrics.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)

    @app.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/config", tags=["meta"])
    async def config():
        s = get_settings()
        return {
            "data_dir": str(s.data_dir),
            "device": s.device,
            "whisper_model": s.whisper_model,
            "separation_preset": s.separation_preset,
            "separation_model": s.separation_model,
            "enable_scraping_providers": s.enable_scraping_providers,
        }

    return app


app = create_app()


def cli() -> None:
    """Console entry point: `karaoke-server`."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    uvicorn.run(
        "karaoke_server.main:app", host=settings.host, port=settings.port, reload=False
    )
