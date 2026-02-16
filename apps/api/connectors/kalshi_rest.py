from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from normalization.canonical import VenueMarket, build_venue_market
from settings import Settings

logger = logging.getLogger(__name__)


class KalshiRestClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout_sec)
        self._last_fetch_ts = 0.0
        self._cache: list[VenueMarket] = []

    async def close(self) -> None:
        await self._client.aclose()

    async def discover_markets(self, force: bool = False) -> list[VenueMarket]:
        now = time.time()
        if not force and self._cache and now - self._last_fetch_ts < 30:
            return self._cache

        url = f"{self.settings.kalshi_rest_base_url.rstrip('/')}/markets"
        params = {"status": "open", "limit": self.settings.market_discovery_limit}

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.exception("failed to fetch kalshi markets")
            return self._cache

        items = payload.get("markets") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            items = []

        markets: list[VenueMarket] = []
        for item in items:
            ticker = str(item.get("ticker") or item.get("market_ticker") or "").strip()
            title = str(item.get("title") or item.get("subtitle") or "").strip()
            if not ticker or not title:
                continue

            outcomes = ["YES", "NO"]
            start_time = (
                item.get("open_time")
                or item.get("event_start_time")
                or item.get("close_time")
                or item.get("expiration_time")
            )

            tags = [
                str(item.get("series_ticker") or ""),
                str(item.get("event_ticker") or ""),
                str(item.get("category") or ""),
            ]
            tags = [tag for tag in tags if tag]

            sport_hint, competition_hint = _infer_sport_comp(item, title)
            market = build_venue_market(
                venue="KALSHI",
                venue_market_id=ticker,
                title=title,
                outcomes=outcomes,
                start_time=start_time,
                sport_hint=sport_hint,
                competition_hint=competition_hint,
                category=str(item.get("category") or ""),
                tags=tags,
                raw=item,
            )
            markets.append(market)

        self._cache = markets
        self._last_fetch_ts = now
        logger.info("kalshi discovery completed", extra={"context": {"count": len(markets)}})
        return markets


def _infer_sport_comp(item: dict[str, Any], title: str) -> tuple[str | None, str | None]:
    text = " ".join(
        [
            title.lower(),
            str(item.get("series_ticker") or "").lower(),
            str(item.get("event_ticker") or "").lower(),
            str(item.get("subtitle") or "").lower(),
        ]
    )

    if "nba" in text or "basketball" in text:
        return "NBA", "NBA"
    if any(word in text for word in ["epl", "premier"]):
        return "SOCCER", "EPL"
    if any(word in text for word in ["ucl", "champions league"]):
        return "SOCCER", "UCL"
    if any(word in text for word in ["uel", "europa league"]):
        return "SOCCER", "UEL"
    if any(word in text for word in ["laliga", "la liga"]):
        return "SOCCER", "LALIGA"
    return None, None
