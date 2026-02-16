from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from engine.orderbook import OrderBookService
from engine.pricing import Quote, compute_edge, suggested_size
from models import BindingStatus, CanonicalEvent, MarketBinding, MispricingSignal
from settings import Settings


@dataclass(slots=True)
class BindingPair:
    event: CanonicalEvent
    poly: MarketBinding
    kalshi: MarketBinding


def refresh_signals(session: Session, settings: Settings) -> list[MispricingSignal]:
    now = datetime.now(timezone.utc)
    earliest = now + timedelta(seconds=settings.min_seconds_to_start)

    pairs = _load_binding_pairs(session)
    created: list[MispricingSignal] = []

    for pair in pairs:
        if pair.event.start_time_utc < earliest:
            continue

        for outcome in ("YES", "NO"):
            signal = _evaluate_pair(session, settings, pair, outcome)
            if signal is None:
                continue
            _upsert_signal(session, signal)
            created.append(signal)

    session.commit()
    return created


def _load_binding_pairs(session: Session) -> list[BindingPair]:
    allowed = {BindingStatus.AUTO.value, BindingStatus.OVERRIDE.value}

    events = session.query(CanonicalEvent).all()
    pairs: list[BindingPair] = []
    for event in events:
        bindings = (
            session.query(MarketBinding)
            .filter(MarketBinding.canonical_event_id == event.id)
            .filter(MarketBinding.status.in_(allowed))
            .all()
        )

        poly = next((row for row in bindings if row.venue == "POLY"), None)
        kalshi = next((row for row in bindings if row.venue == "KALSHI"), None)
        if not poly or not kalshi:
            continue
        if poly.market_type != "WINNER_BINARY" or kalshi.market_type != "WINNER_BINARY":
            continue

        pairs.append(BindingPair(event=event, poly=poly, kalshi=kalshi))

    return pairs


def _get_quote(session: Session, *, venue: str, market_id: str, outcome: str) -> Quote | None:
    top = OrderBookService.get_top(session, venue=venue, venue_market_id=market_id, outcome=outcome)
    if top:
        return Quote(
            bid=top.best_bid,
            ask=top.best_ask,
            bid_size=top.bid_size,
            ask_size=top.ask_size,
        )

    # Binary markets may only expose YES; derive NO conservatively when needed.
    if outcome == "NO":
        yes_top = OrderBookService.get_top(session, venue=venue, venue_market_id=market_id, outcome="YES")
        if yes_top:
            return Quote(
                bid=max(0.0, 1.0 - yes_top.best_ask),
                ask=max(0.0, 1.0 - yes_top.best_bid),
                bid_size=yes_top.ask_size,
                ask_size=yes_top.bid_size,
            )
    return None


def _evaluate_pair(
    session: Session,
    settings: Settings,
    pair: BindingPair,
    outcome: str,
) -> MispricingSignal | None:
    poly_quote = _get_quote(session, venue="POLY", market_id=pair.poly.venue_market_id, outcome=outcome)
    kalshi_quote = _get_quote(session, venue="KALSHI", market_id=pair.kalshi.venue_market_id, outcome=outcome)

    if not poly_quote or not kalshi_quote:
        return None

    a_to_b = compute_edge(
        buy_quote=poly_quote,
        sell_quote=kalshi_quote,
        buy_venue="POLY",
        sell_venue="KALSHI",
        settings=settings,
    )
    b_to_a = compute_edge(
        buy_quote=kalshi_quote,
        sell_quote=poly_quote,
        buy_venue="KALSHI",
        sell_venue="POLY",
        settings=settings,
    )

    if a_to_b.edge_after_costs >= b_to_a.edge_after_costs:
        buy_venue = "POLY"
        sell_venue = "KALSHI"
        buy_market_id = pair.poly.venue_market_id
        sell_market_id = pair.kalshi.venue_market_id
        buy_quote = poly_quote
        sell_quote = kalshi_quote
        edge = a_to_b
    else:
        buy_venue = "KALSHI"
        sell_venue = "POLY"
        buy_market_id = pair.kalshi.venue_market_id
        sell_market_id = pair.poly.venue_market_id
        buy_quote = kalshi_quote
        sell_quote = poly_quote
        edge = b_to_a

    size = suggested_size(
        buy_quote=buy_quote,
        sell_quote=sell_quote,
        max_notional_per_event=settings.max_notional_per_event,
        depth_multiplier=settings.depth_multiplier,
    )
    if size <= 0:
        return None

    if buy_quote.ask_size < size * settings.depth_multiplier:
        return None
    if sell_quote.bid_size < size * settings.depth_multiplier:
        return None

    if edge.edge_after_costs < settings.min_edge:
        return None

    confidence = round(min(pair.poly.confidence, pair.kalshi.confidence), 4)
    return MispricingSignal(
        canonical_event_id=pair.event.id,
        outcome=outcome,
        buy_venue=buy_venue,
        sell_venue=sell_venue,
        buy_market_id=buy_market_id,
        sell_market_id=sell_market_id,
        buy_price=buy_quote.ask,
        sell_price=sell_quote.bid,
        size_suggested=size,
        edge_raw=edge.edge_raw,
        edge_after_costs=edge.edge_after_costs,
        confidence=confidence,
        status="OPEN",
    )


def _upsert_signal(session: Session, signal: MispricingSignal) -> None:
    stmt = insert(MispricingSignal).values(
        canonical_event_id=signal.canonical_event_id,
        outcome=signal.outcome,
        buy_venue=signal.buy_venue,
        sell_venue=signal.sell_venue,
        buy_market_id=signal.buy_market_id,
        sell_market_id=signal.sell_market_id,
        buy_price=signal.buy_price,
        sell_price=signal.sell_price,
        size_suggested=signal.size_suggested,
        edge_raw=signal.edge_raw,
        edge_after_costs=signal.edge_after_costs,
        confidence=signal.confidence,
        status=signal.status,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["canonical_event_id", "outcome", "buy_venue", "sell_venue"],
        set_={
            "buy_market_id": signal.buy_market_id,
            "sell_market_id": signal.sell_market_id,
            "buy_price": signal.buy_price,
            "sell_price": signal.sell_price,
            "size_suggested": signal.size_suggested,
            "edge_raw": signal.edge_raw,
            "edge_after_costs": signal.edge_after_costs,
            "confidence": signal.confidence,
            "status": signal.status,
            "created_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)
