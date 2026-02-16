from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from engine.orderbook import OrderBookService
from models import CanonicalEvent, PaperPosition, PaperPositionStatus, PortfolioSnapshot


def mark_to_market(session: Session) -> None:
    positions = session.query(PaperPosition).filter(PaperPosition.status == PaperPositionStatus.OPEN.value).all()
    for position in positions:
        buy_book = OrderBookService.get_top(
            session,
            venue=position.buy_venue,
            venue_market_id=position.buy_market_id,
            outcome=position.outcome,
        )
        sell_book = OrderBookService.get_top(
            session,
            venue=position.sell_venue,
            venue_market_id=position.sell_market_id,
            outcome=position.outcome,
        )

        if not buy_book or not sell_book:
            position.unrealized_pnl = 0.0
            continue

        pnl_buy = (buy_book.best_bid - position.entry_buy_price) * position.size
        pnl_sell = (position.entry_sell_price - sell_book.best_ask) * position.size
        position.unrealized_pnl = pnl_buy + pnl_sell

    realized = (
        session.query(func.coalesce(func.sum(PaperPosition.realized_pnl), 0.0))
        .filter(PaperPosition.status == PaperPositionStatus.CLOSED.value)
        .scalar()
        or 0.0
    )
    unrealized = (
        session.query(func.coalesce(func.sum(PaperPosition.unrealized_pnl), 0.0))
        .filter(PaperPosition.status == PaperPositionStatus.OPEN.value)
        .scalar()
        or 0.0
    )

    session.add(
        PortfolioSnapshot(
            ts=datetime.now(timezone.utc),
            equity=realized + unrealized,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
        )
    )


def auto_close_started_events(session: Session) -> int:
    now = datetime.now(timezone.utc)
    open_positions = session.query(PaperPosition).filter(PaperPosition.status == PaperPositionStatus.OPEN.value).all()
    closed = 0

    for position in open_positions:
        event = session.query(CanonicalEvent).filter(CanonicalEvent.id == position.canonical_event_id).one_or_none()
        if not event:
            continue
        if event.start_time_utc > now:
            continue

        # Settlement simplification: pair payout nets to locked spread.
        position.realized_pnl = (position.entry_sell_price - position.entry_buy_price) * position.size
        position.unrealized_pnl = 0.0
        position.status = PaperPositionStatus.CLOSED.value
        position.closed_at = now
        closed += 1

    return closed
