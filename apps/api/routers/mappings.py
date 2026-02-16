from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_session
from models import BindingStatus, CanonicalEvent, MarketBinding

router = APIRouter(prefix="/mappings", tags=["mappings"])


class OverrideRequest(BaseModel):
    poly_market_id: str
    kalshi_market_id: str
    canonical_event_id: str | None = None


@router.get("")
def list_mappings(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.query(MarketBinding).order_by(MarketBinding.updated_at.desc()).all()
    return [_serialize_binding(row) for row in rows]


@router.get("/review")
def review_mappings(session: Session = Depends(get_session)) -> list[dict]:
    rows = (
        session.query(MarketBinding)
        .filter(MarketBinding.status == BindingStatus.REVIEW.value)
        .order_by(MarketBinding.updated_at.desc())
        .all()
    )
    return [_serialize_binding(row) for row in rows]


@router.post("/{binding_id}/approve")
def approve_mapping(binding_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.query(MarketBinding).filter(MarketBinding.id == binding_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="mapping not found")

    row.status = BindingStatus.OVERRIDE.value
    row.confidence = max(0.9, row.confidence)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return _serialize_binding(row)


@router.post("/{binding_id}/reject")
def reject_mapping(binding_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.query(MarketBinding).filter(MarketBinding.id == binding_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="mapping not found")

    row.status = BindingStatus.REJECTED.value
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return _serialize_binding(row)


@router.post("/override")
def override_pair(payload: OverrideRequest, session: Session = Depends(get_session)) -> dict:
    poly = (
        session.query(MarketBinding)
        .filter(MarketBinding.venue == "POLY", MarketBinding.venue_market_id == payload.poly_market_id)
        .one_or_none()
    )
    kalshi = (
        session.query(MarketBinding)
        .filter(MarketBinding.venue == "KALSHI", MarketBinding.venue_market_id == payload.kalshi_market_id)
        .one_or_none()
    )

    if not poly or not kalshi:
        raise HTTPException(status_code=404, detail="pair not found")

    canonical_event_id = payload.canonical_event_id or poly.canonical_event_id or kalshi.canonical_event_id
    event = session.query(CanonicalEvent).filter(CanonicalEvent.id == canonical_event_id).one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="canonical event not found")

    evidence = {
        "manual_override": True,
        "poly_market_id": payload.poly_market_id,
        "kalshi_market_id": payload.kalshi_market_id,
    }

    for row in (poly, kalshi):
        row.canonical_event_id = canonical_event_id
        row.status = BindingStatus.OVERRIDE.value
        row.confidence = 1.0
        row.evidence_json = json.dumps(evidence)
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)

    session.commit()

    return {
        "status": "ok",
        "canonical_event_id": canonical_event_id,
        "poly": _serialize_binding(poly),
        "kalshi": _serialize_binding(kalshi),
    }


def _serialize_binding(row: MarketBinding) -> dict:
    return {
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
