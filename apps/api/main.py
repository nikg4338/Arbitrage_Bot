from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from engine.scheduler import AppScheduler
from logging import configure_logging
from routers import health, mappings, markets, paper, signals
from settings import get_settings

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = AppScheduler(settings)
    app.state.scheduler = scheduler
    await scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(markets.router)
app.include_router(mappings.router)
app.include_router(signals.router)
app.include_router(paper.router)
