from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from models import OrderBookTop


class OrderBookService:
    @staticmethod
    def upsert_top(
        session: Session,
        *,
        venue: str,
        venue_market_id: str,
        outcome: str,
        best_bid: float,
        best_ask: float,
        bid_size: float,
        ask_size: float,
    ) -> None:
        now = datetime.now(timezone.utc)
        stmt = insert(OrderBookTop).values(
            venue=venue,
            venue_market_id=venue_market_id,
            outcome=outcome,
            best_bid=float(best_bid),
            best_ask=float(best_ask),
            bid_size=float(bid_size),
            ask_size=float(ask_size),
            ts=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["venue", "venue_market_id", "outcome"],
            set_={
                "best_bid": float(best_bid),
                "best_ask": float(best_ask),
                "bid_size": float(bid_size),
                "ask_size": float(ask_size),
                "ts": now,
            },
        )
        session.execute(stmt)

    @staticmethod
    def get_top(session: Session, *, venue: str, venue_market_id: str, outcome: str) -> OrderBookTop | None:
        return (
            session.query(OrderBookTop)
            .filter(
                OrderBookTop.venue == venue,
                OrderBookTop.venue_market_id == venue_market_id,
                OrderBookTop.outcome == outcome,
            )
            .one_or_none()
        )
