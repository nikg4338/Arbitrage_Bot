from __future__ import annotations

import math
from dataclasses import dataclass

from engine.fees import total_fee_rate
from settings import Settings

TICK_SIZE = 0.01


@dataclass(slots=True)
class Quote:
    bid: float
    ask: float
    bid_size: float
    ask_size: float


@dataclass(slots=True)
class EdgeComputation:
    edge_raw: float
    edge_after_costs: float
    fee_component: float
    slippage_component: float


def compute_edge(
    *,
    buy_quote: Quote,
    sell_quote: Quote,
    buy_venue: str,
    sell_venue: str,
    settings: Settings,
) -> EdgeComputation:
    edge_raw = sell_quote.bid - buy_quote.ask
    spread = max(0.0, max(buy_quote.ask - buy_quote.bid, sell_quote.ask - sell_quote.bid))
    slippage = max(TICK_SIZE, spread * settings.slippage_k)
    fees = (buy_quote.ask + sell_quote.bid) * total_fee_rate(buy_venue, sell_venue, settings)

    edge_after_costs = edge_raw - fees - slippage
    return EdgeComputation(
        edge_raw=edge_raw,
        edge_after_costs=edge_after_costs,
        fee_component=fees,
        slippage_component=slippage,
    )


def suggested_size(
    *,
    buy_quote: Quote,
    sell_quote: Quote,
    max_notional_per_event: float,
    depth_multiplier: float,
) -> float:
    visible_depth = min(buy_quote.ask_size, sell_quote.bid_size)
    if visible_depth <= 0:
        return 0.0

    by_depth = visible_depth / max(depth_multiplier, 1.0)
    best_price = max(buy_quote.ask, 0.01)
    by_notional = max_notional_per_event / best_price
    raw_size = max(0.0, min(by_depth, by_notional))

    # Floor (not round) to avoid tiny depth-overrun artifacts in strict depth checks.
    return math.floor(raw_size * 10_000) / 10_000
