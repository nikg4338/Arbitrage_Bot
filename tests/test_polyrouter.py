from __future__ import annotations

import asyncio
from typing import Any

from connectors.polyrouter import PolyrouterClient
from engine.scheduler import AppScheduler
from normalization.canonical import VenueMarket, build_venue_market
from settings import Settings


def _sample_market(*, venue: str, market_id: str) -> VenueMarket:
    return build_venue_market(
        venue=venue,
        venue_market_id=market_id,
        title="Boston Celtics vs New York Knicks",
        outcomes=["YES", "NO"],
        start_time="2030-01-01T00:00:00Z",
        sport_hint="NBA",
        competition_hint="NBA",
        raw={},
    )


def test_polyrouter_market_parsing_filters_and_maps_platform(monkeypatch) -> None:
    settings = Settings(
        polyrouter_enable=True,
        polyrouter_api_key="test-key",
        polyrouter_market_page_limit=3,
        market_discovery_limit=20,
    )
    client = PolyrouterClient(settings)

    payloads = [
        {
            "data": [
                {
                    "id": "pr-nba-1",
                    "condition_id": "cond-nba-1",
                    "title": "Boston Celtics vs New York Knicks Winner?",
                    "sport": "NBA",
                    "outcomes": ["Yes", "No"],
                    "start_time": "2030-01-01T00:00:00Z",
                },
                {
                    "id": "pr-prop-1",
                    "condition_id": "cond-prop-1",
                    "title": "LeBron James points over/under",
                    "sport": "NBA",
                    "outcomes": ["Over", "Under"],
                    "start_time": "2030-01-01T00:00:00Z",
                },
                {
                    "id": "pr-epl-1",
                    "condition_id": "cond-epl-1",
                    "title": "Arsenal vs Liverpool Winner?",
                    "league": "EPL",
                    "outcomes": ["Yes", "No"],
                    "start_time": "2030-01-02T00:00:00Z",
                },
            ],
            "next_cursor": "cursor-2",
        },
        {
            "data": [
                {
                    "id": "pr-ucl-1",
                    "condition_id": "cond-ucl-1",
                    "title": "Real Madrid vs Barcelona Winner?",
                    "competition": "UCL",
                    "outcomes": ["Yes", "No"],
                    "start_time": "2030-01-03T00:00:00Z",
                }
            ]
        },
    ]

    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_request(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, params))
        if payloads:
            return payloads.pop(0)
        return {"data": []}

    monkeypatch.setattr(client, "_request_with_backoff", fake_request)

    try:
        markets = asyncio.run(client.discover_markets_by_platform("polymarket", force=True))
    finally:
        asyncio.run(client.close())

    assert len(markets) == 3
    assert {market.venue for market in markets} == {"POLY"}
    assert {market.venue_market_id for market in markets} == {"cond-nba-1", "cond-epl-1", "cond-ucl-1"}
    assert all(market.market_type == "WINNER_BINARY" for market in markets)
    assert calls[0][0] == "/markets"
    assert calls[0][1]["platform"] == "polymarket"


def test_polyrouter_orderbook_batching_and_native_id_mapping(monkeypatch) -> None:
    settings = Settings(
        polyrouter_enable=True,
        polyrouter_api_key="test-key",
        polyrouter_orderbook_batch_size=2,
    )
    client = PolyrouterClient(settings)
    client._lookup_to_native = {
        ("polymarket", "lookup-1"): "cond-1",
        ("polymarket", "lookup-2"): "cond-2",
        ("polymarket", "lookup-3"): "cond-3",
    }

    payloads = [
        {
            "data": [
                {
                    "market_id": "lookup-1",
                    "best_bid": 0.44,
                    "best_ask": 0.46,
                    "bid_size": 120,
                    "ask_size": 130,
                },
                {
                    "market_id": "lookup-2",
                    "bids": [[0.51, 200]],
                    "asks": [[0.53, 190]],
                },
            ]
        },
        {
            "data": [
                {
                    "market_id": "lookup-3",
                    "yes_bid": 48,
                    "yes_ask": 52,
                    "yes_bid_size": 95,
                    "yes_ask_size": 90,
                }
            ]
        },
    ]

    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_request(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, params))
        return payloads.pop(0)

    monkeypatch.setattr(client, "_request_with_backoff", fake_request)

    try:
        books = asyncio.run(client.fetch_orderbooks("polymarket", ["lookup-1", "lookup-2", "lookup-3"]))
    finally:
        asyncio.run(client.close())

    assert len(calls) == 2
    assert calls[0][0] == "/orderbooks"
    assert calls[0][1]["market_ids"] == "lookup-1,lookup-2"
    assert calls[1][1]["market_ids"] == "lookup-3"
    assert len(books) == 3
    assert {row["venue"] for row in books} == {"POLY"}
    assert {row["venue_market_id"] for row in books} == {"cond-1", "cond-2", "cond-3"}
    assert next(row for row in books if row["venue_market_id"] == "cond-3")["best_bid"] == 0.48


def test_polyrouter_retries_after_rate_limit(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, status_code: int, payload: Any) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400 and self.status_code != 429:
                raise RuntimeError(f"status {self.status_code}")

    class FakeHTTPClient:
        def __init__(self) -> None:
            self.calls = 0
            self.responses = [
                FakeResponse(429, {"error": "rate limited"}),
                FakeResponse(200, {"data": [{"id": "ok"}]}),
            ]

        async def get(self, *_args, **_kwargs) -> FakeResponse:
            self.calls += 1
            return self.responses.pop(0)

        async def aclose(self) -> None:
            return None

    settings = Settings(polyrouter_enable=True, polyrouter_api_key="test-key")
    client = PolyrouterClient(settings)
    fake_http = FakeHTTPClient()
    client._client = fake_http  # type: ignore[assignment]

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_rate_limit() -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(client, "_respect_rate_limit", fake_rate_limit)

    try:
        payload = asyncio.run(client._request_with_backoff("/markets", params={"platform": "polymarket"}))
    finally:
        asyncio.run(client.close())

    assert payload == {"data": [{"id": "ok"}]}
    assert fake_http.calls == 2
    assert any(delay > 0 for delay in sleep_calls)


def test_scheduler_market_source_direct_vs_polyrouter(monkeypatch) -> None:
    direct_settings = Settings(
        market_data_source="direct",
        polyrouter_enable=False,
    )
    direct_scheduler = AppScheduler(direct_settings)

    direct_calls = {"gamma": 0, "kalshi": 0, "polyrouter": 0}

    async def direct_gamma() -> list[VenueMarket]:
        direct_calls["gamma"] += 1
        return [_sample_market(venue="POLY", market_id="poly-direct-1")]

    async def direct_kalshi() -> list[VenueMarket]:
        direct_calls["kalshi"] += 1
        return [_sample_market(venue="KALSHI", market_id="kalshi-direct-1")]

    async def never_polyrouter(_platform: str) -> list[VenueMarket]:
        direct_calls["polyrouter"] += 1
        return []

    monkeypatch.setattr(direct_scheduler.gamma, "discover_markets", direct_gamma)
    monkeypatch.setattr(direct_scheduler.kalshi_rest, "discover_markets", direct_kalshi)
    monkeypatch.setattr(direct_scheduler.polyrouter, "discover_markets_by_platform", never_polyrouter)

    try:
        direct_poly, direct_kal = asyncio.run(direct_scheduler._discover_markets_from_source("direct"))
    finally:
        asyncio.run(direct_scheduler.stop())

    assert len(direct_poly) == 1
    assert len(direct_kal) == 1
    assert direct_calls == {"gamma": 1, "kalshi": 1, "polyrouter": 0}

    polyrouter_settings = Settings(
        market_data_source="polyrouter",
        polyrouter_enable=True,
        polyrouter_api_key="test-key",
    )
    polyrouter_scheduler = AppScheduler(polyrouter_settings)

    polyrouter_calls = {"gamma": 0, "kalshi": 0, "polyrouter": 0}

    async def never_gamma() -> list[VenueMarket]:
        polyrouter_calls["gamma"] += 1
        return []

    async def never_kalshi() -> list[VenueMarket]:
        polyrouter_calls["kalshi"] += 1
        return []

    async def polyrouter_discovery(platform: str) -> list[VenueMarket]:
        polyrouter_calls["polyrouter"] += 1
        venue = "POLY" if platform == "polymarket" else "KALSHI"
        return [_sample_market(venue=venue, market_id=f"{platform}-market-1")]

    monkeypatch.setattr(polyrouter_scheduler.gamma, "discover_markets", never_gamma)
    monkeypatch.setattr(polyrouter_scheduler.kalshi_rest, "discover_markets", never_kalshi)
    monkeypatch.setattr(polyrouter_scheduler.polyrouter, "discover_markets_by_platform", polyrouter_discovery)

    try:
        polyrouter_poly, polyrouter_kal = asyncio.run(polyrouter_scheduler._discover_markets_from_source("polyrouter"))
    finally:
        asyncio.run(polyrouter_scheduler.stop())

    assert len(polyrouter_poly) == 1
    assert len(polyrouter_kal) == 1
    assert polyrouter_calls == {"gamma": 0, "kalshi": 0, "polyrouter": 2}


def test_polyrouter_default_req_limit_is_safe() -> None:
    settings = Settings()
    assert settings.polyrouter_req_per_min <= 100
