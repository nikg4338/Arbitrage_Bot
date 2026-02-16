from __future__ import annotations

import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from engine.orderbook import OrderBookService
from models import MispricingSignal, PaperFill, PaperPosition, PaperPositionStatus
from paper.fills import simulate_limit_fill


class PaperTradingSimulator:
    def simulate_signal(self, session: Session, signal_id: str, requested_size: float | None = None) -> PaperPosition:
        signal = session.query(MispricingSignal).filter(MispricingSignal.id == signal_id).one_or_none()
        if signal is None:
            raise ValueError("signal not found")

        target_size = requested_size if requested_size is not None else signal.size_suggested
        target_size = max(0.0, min(target_size, signal.size_suggested))
        if target_size <= 0:
            raise ValueError("size must be positive")

        buy_top = OrderBookService.get_top(
            session,
            venue=signal.buy_venue,
            venue_market_id=signal.buy_market_id,
            outcome=signal.outcome,
        )
        sell_top = OrderBookService.get_top(
            session,
            venue=signal.sell_venue,
            venue_market_id=signal.sell_market_id,
            outcome=signal.outcome,
        )

        if not buy_top or not sell_top:
            raise ValueError("orderbook unavailable for simulation")

        rng = random.Random(f"{signal.id}:{target_size}")

        buy_fill = simulate_limit_fill(
            side="BUY",
            limit_price=signal.buy_price,
            best_bid=buy_top.best_bid,
            best_ask=buy_top.best_ask,
            displayed_depth=buy_top.ask_size,
            requested_size=target_size,
            rng=rng,
        )
        sell_fill = simulate_limit_fill(
            side="SELL",
            limit_price=signal.sell_price,
            best_bid=sell_top.best_bid,
            best_ask=sell_top.best_ask,
            displayed_depth=sell_top.bid_size,
            requested_size=target_size,
            rng=rng,
        )

        filled_size = min(buy_fill.filled_size, sell_fill.filled_size)
        if filled_size <= 0:
            raise ValueError("simulated fills were zero")

        position = PaperPosition(
            canonical_event_id=signal.canonical_event_id,
            signal_id=signal.id,
            outcome=signal.outcome,
            buy_venue=signal.buy_venue,
            sell_venue=signal.sell_venue,
            buy_market_id=signal.buy_market_id,
            sell_market_id=signal.sell_market_id,
            size=filled_size,
            entry_buy_price=buy_fill.fill_price,
            entry_sell_price=sell_fill.fill_price,
            fill_ratio=filled_size / target_size,
            status=PaperPositionStatus.OPEN.value,
        )
        session.add(position)
        session.flush()

        session.add(
            PaperFill(
                position_id=position.id,
                leg="BUY",
                side="BUY",
                limit_price=signal.buy_price,
                fill_price=buy_fill.fill_price,
                size=target_size,
                filled_size=filled_size,
                probability=buy_fill.probability,
            )
        )
        session.add(
            PaperFill(
                position_id=position.id,
                leg="SELL",
                side="SELL",
                limit_price=signal.sell_price,
                fill_price=sell_fill.fill_price,
                size=target_size,
                filled_size=filled_size,
                probability=sell_fill.probability,
            )
        )

        return position

    def close_position(self, session: Session, position_id: str) -> PaperPosition:
        position = session.query(PaperPosition).filter(PaperPosition.id == position_id).one_or_none()
        if position is None:
            raise ValueError("position not found")
        if position.status == PaperPositionStatus.CLOSED.value:
            return position

        buy_top = OrderBookService.get_top(
            session,
            venue=position.buy_venue,
            venue_market_id=position.buy_market_id,
            outcome=position.outcome,
        )
        sell_top = OrderBookService.get_top(
            session,
            venue=position.sell_venue,
            venue_market_id=position.sell_market_id,
            outcome=position.outcome,
        )

        if buy_top and sell_top:
            pnl_buy = (buy_top.best_bid - position.entry_buy_price) * position.size
            pnl_sell = (position.entry_sell_price - sell_top.best_ask) * position.size
            realized = pnl_buy + pnl_sell
        else:
            realized = (position.entry_sell_price - position.entry_buy_price) * position.size

        position.realized_pnl = realized
        position.unrealized_pnl = 0.0
        position.status = PaperPositionStatus.CLOSED.value
        position.closed_at = datetime.now(timezone.utc)
        return position
