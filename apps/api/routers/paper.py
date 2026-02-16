from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_session
from models import MispricingSignal, PaperFill, PaperPosition, PaperPositionStatus, PortfolioSnapshot
from paper.simulator import PaperTradingSimulator

router = APIRouter(prefix="/paper", tags=["paper"])
simulator = PaperTradingSimulator()


class SimulateRequest(BaseModel):
    signal_id: str
    size: float | None = None


@router.post("/simulate")
def simulate(payload: SimulateRequest, session: Session = Depends(get_session)) -> dict:
    try:
        position = simulator.simulate_signal(session, payload.signal_id, payload.size)
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _serialize_position(position)


@router.get("/positions")
def positions(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.query(PaperPosition).order_by(PaperPosition.opened_at.desc()).all()
    return [_serialize_position(row) for row in rows]


@router.post("/positions/{position_id}/close")
def close_position(position_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        position = simulator.close_position(session, position_id)
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _serialize_position(position)


@router.get("/fills/{position_id}")
def fills(position_id: str, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.query(PaperFill).filter(PaperFill.position_id == position_id).order_by(PaperFill.ts.asc()).all()
    return [
        {
            "id": row.id,
            "position_id": row.position_id,
            "leg": row.leg,
            "side": row.side,
            "limit_price": row.limit_price,
            "fill_price": row.fill_price,
            "size": row.size,
            "filled_size": row.filled_size,
            "probability": row.probability,
            "ts": row.ts.isoformat(),
        }
        for row in rows
    ]


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    closed = session.query(PaperPosition).filter(PaperPosition.status == PaperPositionStatus.CLOSED.value).all()
    open_positions = session.query(PaperPosition).filter(PaperPosition.status == PaperPositionStatus.OPEN.value).all()

    realized = sum(row.realized_pnl for row in closed)
    unrealized = sum(row.unrealized_pnl for row in open_positions)
    wins = [row for row in closed if row.realized_pnl > 0]
    win_rate = (len(wins) / len(closed)) if closed else 0.0
    avg_fill_ratio = (sum(row.fill_ratio for row in closed + open_positions) / (len(closed) + len(open_positions))) if (closed or open_positions) else 0.0

    # Compare captured spread to signal spread as a rough execution quality metric.
    signal_ids = [row.signal_id for row in closed + open_positions]
    signals = {
        row.id: row
        for row in session.query(MispricingSignal)
        .filter(MispricingSignal.id.in_(signal_ids) if signal_ids else False)
        .all()
    }

    captured_edges = []
    slippages = []
    for position in closed + open_positions:
        expected = None
        signal = signals.get(position.signal_id)
        if signal:
            expected = signal.sell_price - signal.buy_price
        captured = position.entry_sell_price - position.entry_buy_price
        captured_edges.append(captured)
        if expected is not None:
            slippages.append(expected - captured)

    avg_edge_captured = sum(captured_edges) / len(captured_edges) if captured_edges else 0.0
    avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0

    latest_equity = (
        session.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
        .one_or_none()
    )

    curve = (
        session.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.ts.asc())
        .limit(200)
        .all()
    )

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "open_positions": len(open_positions),
        "closed_positions": len(closed),
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "equity": (latest_equity.equity if latest_equity else realized + unrealized),
        "win_rate": win_rate,
        "avg_fill_ratio": avg_fill_ratio,
        "avg_edge_captured": avg_edge_captured,
        "avg_slippage": avg_slippage,
        "equity_curve": [
            {
                "ts": row.ts.isoformat(),
                "equity": row.equity,
                "realized": row.realized_pnl,
                "unrealized": row.unrealized_pnl,
            }
            for row in curve
        ],
    }


def _serialize_position(row: PaperPosition) -> dict:
    return {
        "id": row.id,
        "canonical_event_id": row.canonical_event_id,
        "signal_id": row.signal_id,
        "outcome": row.outcome,
        "buy_venue": row.buy_venue,
        "sell_venue": row.sell_venue,
        "buy_market_id": row.buy_market_id,
        "sell_market_id": row.sell_market_id,
        "size": row.size,
        "entry_buy_price": row.entry_buy_price,
        "entry_sell_price": row.entry_sell_price,
        "fill_ratio": row.fill_ratio,
        "status": row.status,
        "opened_at": row.opened_at.isoformat(),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "realized_pnl": row.realized_pnl,
        "unrealized_pnl": row.unrealized_pnl,
    }
