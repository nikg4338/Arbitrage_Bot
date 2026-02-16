from __future__ import annotations

from datetime import datetime, timedelta, timezone

from normalization.canonical import build_venue_market, canonicalize_team
from normalization.resolver import resolve_markets


def test_man_utd_alias_maps_to_manchester_united() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=6)

    poly = [
        build_venue_market(
            venue="POLY",
            venue_market_id="poly-epl-mun-ars",
            title="Man Utd vs Arsenal",
            outcomes=["YES", "NO"],
            start_time=start,
            sport_hint="SOCCER",
            competition_hint="EPL",
            raw={},
        )
    ]
    kalshi = [
        build_venue_market(
            venue="KALSHI",
            venue_market_id="kalshi-epl-mun-ars",
            title="Manchester United vs Arsenal",
            outcomes=["YES", "NO"],
            start_time=start,
            sport_hint="SOCCER",
            competition_hint="EPL",
            raw={},
        )
    ]

    pairs = resolve_markets(poly, kalshi)
    assert len(pairs) == 1
    assert pairs[0].status == "AUTO"
    assert "manchester united" in pairs[0].title_canonical


def test_orientation_flip_for_binary_markets_goes_to_review() -> None:
    start = datetime.now(timezone.utc) + timedelta(hours=8)

    poly = [
        build_venue_market(
            venue="POLY",
            venue_market_id="poly-ucl-rma-bar",
            title="Real Madrid vs Barcelona",
            outcomes=["YES", "NO"],
            start_time=start,
            sport_hint="SOCCER",
            competition_hint="UCL",
            raw={},
        )
    ]
    kalshi = [
        build_venue_market(
            venue="KALSHI",
            venue_market_id="kalshi-ucl-rma-bar",
            title="Barcelona vs Real Madrid",
            outcomes=["YES", "NO"],
            start_time=start,
            sport_hint="SOCCER",
            competition_hint="UCL",
            raw={},
        )
    ]

    pairs = resolve_markets(poly, kalshi)
    assert len(pairs) == 1
    assert pairs[0].status == "REVIEW"


def test_spurs_alias_disambiguates_by_sport() -> None:
    assert canonicalize_team("NBA", "Spurs") == "san antonio spurs"
    assert canonicalize_team("SOCCER", "Spurs") == "tottenham hotspur"


def test_time_window_blocks_far_nba_matches() -> None:
    poly_start = datetime.now(timezone.utc) + timedelta(hours=4)
    kalshi_start = poly_start + timedelta(hours=8)

    poly = [
        build_venue_market(
            venue="POLY",
            venue_market_id="poly-nba-a",
            title="Boston Celtics vs New York Knicks",
            outcomes=["YES", "NO"],
            start_time=poly_start,
            sport_hint="NBA",
            competition_hint="NBA",
            raw={},
        )
    ]
    kalshi = [
        build_venue_market(
            venue="KALSHI",
            venue_market_id="kalshi-nba-a",
            title="Boston Celtics vs New York Knicks",
            outcomes=["YES", "NO"],
            start_time=kalshi_start,
            sport_hint="NBA",
            competition_hint="NBA",
            raw={},
        )
    ]

    pairs = resolve_markets(poly, kalshi)
    assert pairs == []
