from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(slots=True)
class FillResult:
    fill_price: float
    filled_size: float
    probability: float


def simulate_limit_fill(
    *,
    side: str,
    limit_price: float,
    best_bid: float,
    best_ask: float,
    displayed_depth: float,
    requested_size: float,
    rng: random.Random,
) -> FillResult:
    side = side.upper()
    requested_size = max(0.0, requested_size)
    if requested_size <= 0 or displayed_depth <= 0:
        return FillResult(fill_price=limit_price, filled_size=0.0, probability=0.0)

    if side == "BUY":
        if limit_price >= best_ask:
            filled = min(requested_size, displayed_depth)
            return FillResult(fill_price=best_ask, filled_size=filled, probability=1.0)
        if abs(limit_price - best_bid) < 1e-9:
            prob = 0.60
        elif best_bid < limit_price < best_ask:
            prob = 0.12
        else:
            prob = 0.03
    else:
        if limit_price <= best_bid:
            filled = min(requested_size, displayed_depth)
            return FillResult(fill_price=best_bid, filled_size=filled, probability=1.0)
        if abs(limit_price - best_ask) < 1e-9:
            prob = 0.60
        elif best_bid < limit_price < best_ask:
            prob = 0.12
        else:
            prob = 0.03

    if rng.random() <= prob:
        size = min(requested_size, displayed_depth * prob)
    else:
        size = 0.0
    return FillResult(fill_price=limit_price, filled_size=size, probability=prob)
