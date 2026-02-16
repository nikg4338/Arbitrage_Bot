from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_session
from models import CanonicalEvent, MarketBinding, OrderBookTop

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("/events")
def list_events(
    sport: str | None = Query(default=None),
    competition: str | None = Query(default=None),
    starts_before: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    query = session.query(CanonicalEvent)
    if sport:
        query = query.filter(CanonicalEvent.sport == sport)
    if competition:
        query = query.filter(CanonicalEvent.competition == competition)
    if starts_before:
        query = query.filter(CanonicalEvent.start_time_utc <= starts_before)

    rows = query.order_by(CanonicalEvent.start_time_utc.asc()).all()
    return [
        {
            "id": row.id,
            "sport": row.sport,
            "competition": row.competition,
            "start_time_utc": row.start_time_utc.isoformat(),
            "home_team": row.home_team,
            "away_team": row.away_team,
            "title_canonical": row.title_canonical,
        }
        for row in rows
    ]


@router.get("/{event_id}/bindings")
def event_bindings(event_id: str, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.query(MarketBinding).filter(MarketBinding.canonical_event_id == event_id).all()
    return [
        {
            "id": row.id,
            "canonical_event_id": row.canonical_event_id,
            "venue": row.venue,
            "venue_market_id": row.venue_market_id,
            "market_type": row.market_type,
            "status": row.status,
            "confidence": row.confidence,
            "evidence_json": row.evidence_json,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/orderbooks")
def list_orderbooks(
    venue: str | None = Query(default=None),
    market_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    query = session.query(OrderBookTop)
    if venue:
        query = query.filter(OrderBookTop.venue == venue)
    if market_id:
        query = query.filter(OrderBookTop.venue_market_id == market_id)

    rows = query.order_by(OrderBookTop.ts.desc()).limit(300).all()
    return [
        {
            "venue": row.venue,
            "venue_market_id": row.venue_market_id,
            "outcome": row.outcome,
            "best_bid": row.best_bid,
            "best_ask": row.best_ask,
            "bid_size": row.bid_size,
            "ask_size": row.ask_size,
            "ts": row.ts.isoformat(),
        }
        for row in rows
    ]
