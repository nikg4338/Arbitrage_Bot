from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from db import get_session
from models import CanonicalEvent, MispricingSignal
from settings import get_settings

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(
    min_edge: float = Query(default=0.0),
    sport: str | None = Query(default=None),
    competition: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    settings = get_settings()
    query = session.query(MispricingSignal).filter(MispricingSignal.status == "OPEN")
    if not settings.enable_demo_fallback:
        query = query.filter(
            ~MispricingSignal.buy_market_id.like("%demo%"),
            ~MispricingSignal.sell_market_id.like("%demo%"),
        )
    if min_edge > 0:
        query = query.filter(MispricingSignal.edge_after_costs >= min_edge)

    rows = query.order_by(MispricingSignal.edge_after_costs.desc()).limit(200).all()
    event_ids = [row.canonical_event_id for row in rows]
    events = (
        session.query(CanonicalEvent)
        .filter(CanonicalEvent.id.in_(event_ids) if event_ids else False)
        .all()
    )
    event_map = {event.id: event for event in events}

    payload: list[dict] = []
    for row in rows:
        event = event_map.get(row.canonical_event_id)
        if sport and (event is None or event.sport != sport):
            continue
        if competition and (event is None or event.competition != competition):
            continue

        payload.append(
            {
                "id": row.id,
                "canonical_event_id": row.canonical_event_id,
                "sport": event.sport if event else None,
                "competition": event.competition if event else None,
                "match": event.title_canonical if event else row.canonical_event_id,
                "start_time_utc": event.start_time_utc.isoformat() if event else None,
                "outcome": row.outcome,
                "buy_venue": row.buy_venue,
                "sell_venue": row.sell_venue,
                "buy_market_id": row.buy_market_id,
                "sell_market_id": row.sell_market_id,
                "buy_price": row.buy_price,
                "sell_price": row.sell_price,
                "size_suggested": row.size_suggested,
                "edge_raw": row.edge_raw,
                "edge_after_costs": row.edge_after_costs,
                "confidence": row.confidence,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
        )
    return payload


@router.get("/snapshot")
def snapshot(request: Request) -> dict:
    scheduler = request.app.state.scheduler
    return scheduler.latest_snapshot()


@router.websocket("/ws")
async def ws_signals(websocket: WebSocket) -> None:
    scheduler = websocket.app.state.scheduler
    await scheduler.hub.connect(websocket)
    try:
        await websocket.send_json(scheduler.latest_snapshot())
        while True:
            # Keep connection alive and detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await scheduler.hub.disconnect(websocket)
    except Exception:
        await scheduler.hub.disconnect(websocket)
