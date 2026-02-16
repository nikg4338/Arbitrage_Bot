from __future__ import annotations

from settings import Settings


def venue_fee_rate(venue: str, settings: Settings) -> float:
    if venue == "POLY":
        return settings.fee_poly_bps / 10_000.0
    if venue == "KALSHI":
        return settings.fee_kalshi_bps / 10_000.0
    return 0.0


def total_fee_rate(buy_venue: str, sell_venue: str, settings: Settings) -> float:
    return venue_fee_rate(buy_venue, settings) + venue_fee_rate(sell_venue, settings)
