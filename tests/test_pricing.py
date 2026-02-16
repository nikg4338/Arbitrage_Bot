from __future__ import annotations

from engine.pricing import Quote, compute_edge
from settings import Settings


def test_edge_after_costs_is_not_positive_when_raw_is_too_small() -> None:
    settings = Settings(min_edge=0.0, slippage_k=0.2, fee_poly_bps=40, fee_kalshi_bps=35)

    result = compute_edge(
        buy_quote=Quote(bid=0.49, ask=0.50, bid_size=100, ask_size=100),
        sell_quote=Quote(bid=0.505, ask=0.515, bid_size=100, ask_size=100),
        buy_venue="POLY",
        sell_venue="KALSHI",
        settings=settings,
    )

    assert result.edge_raw > 0
    assert result.edge_after_costs <= 0


def test_edge_after_costs_positive_when_gap_large() -> None:
    settings = Settings(min_edge=0.0, slippage_k=0.1, fee_poly_bps=10, fee_kalshi_bps=10)

    result = compute_edge(
        buy_quote=Quote(bid=0.30, ask=0.32, bid_size=100, ask_size=100),
        sell_quote=Quote(bid=0.46, ask=0.48, bid_size=100, ask_size=100),
        buy_venue="POLY",
        sell_venue="KALSHI",
        settings=settings,
    )

    assert result.edge_raw > 0
    assert result.edge_after_costs > 0
