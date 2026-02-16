from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from engine.orderbook import OrderBookService
from engine.signaler import refresh_signals
from models import CanonicalEvent, MarketBinding, MispricingSignal
from settings import Settings


def test_only_auto_or_override_bindings_produce_signals() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        start = datetime.now(timezone.utc) + timedelta(hours=4)

        event_auto = CanonicalEvent(
            id="evt-auto",
            sport="NBA",
            competition="NBA",
            start_time_utc=start,
            home_team="boston celtics",
            away_team="new york knicks",
            title_canonical="boston celtics vs new york knicks",
        )
        event_review = CanonicalEvent(
            id="evt-review",
            sport="NBA",
            competition="NBA",
            start_time_utc=start,
            home_team="miami heat",
            away_team="orlando magic",
            title_canonical="miami heat vs orlando magic",
        )
        session.add(event_auto)
        session.add(event_review)

        session.add(
            MarketBinding(
                canonical_event_id="evt-auto",
                venue="POLY",
                venue_market_id="poly-a",
                market_type="WINNER_BINARY",
                status="AUTO",
                confidence=0.95,
                evidence_json="{}",
            )
        )
        session.add(
            MarketBinding(
                canonical_event_id="evt-auto",
                venue="KALSHI",
                venue_market_id="kalshi-a",
                market_type="WINNER_BINARY",
                status="OVERRIDE",
                confidence=1.0,
                evidence_json="{}",
            )
        )

        session.add(
            MarketBinding(
                canonical_event_id="evt-review",
                venue="POLY",
                venue_market_id="poly-r",
                market_type="WINNER_BINARY",
                status="REVIEW",
                confidence=0.83,
                evidence_json="{}",
            )
        )
        session.add(
            MarketBinding(
                canonical_event_id="evt-review",
                venue="KALSHI",
                venue_market_id="kalshi-r",
                market_type="WINNER_BINARY",
                status="AUTO",
                confidence=0.91,
                evidence_json="{}",
            )
        )

        OrderBookService.upsert_top(
            session,
            venue="POLY",
            venue_market_id="poly-a",
            outcome="YES",
            best_bid=0.40,
            best_ask=0.41,
            bid_size=300,
            ask_size=250,
        )
        OrderBookService.upsert_top(
            session,
            venue="KALSHI",
            venue_market_id="kalshi-a",
            outcome="YES",
            best_bid=0.49,
            best_ask=0.50,
            bid_size=300,
            ask_size=250,
        )

        OrderBookService.upsert_top(
            session,
            venue="POLY",
            venue_market_id="poly-r",
            outcome="YES",
            best_bid=0.35,
            best_ask=0.36,
            bid_size=300,
            ask_size=250,
        )
        OrderBookService.upsert_top(
            session,
            venue="KALSHI",
            venue_market_id="kalshi-r",
            outcome="YES",
            best_bid=0.47,
            best_ask=0.48,
            bid_size=300,
            ask_size=250,
        )

        session.commit()

        settings = Settings(min_edge=0.001, slippage_k=0.0, fee_poly_bps=0.0, fee_kalshi_bps=0.0)
        refresh_signals(session, settings)

        signals = session.query(MispricingSignal).all()
        assert signals
        assert all(row.canonical_event_id == "evt-auto" for row in signals)
