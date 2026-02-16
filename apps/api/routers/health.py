from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(request: Request) -> dict:
    scheduler = request.app.state.scheduler
    return {"status": "ok", **scheduler.health_payload()}
