from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from normalization.canonical import VenueMarket, build_venue_market
from settings import Settings

logger = logging.getLogger(__name__)


class PolymarketGammaClient:
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

        url = f"{self.settings.poly_gamma_base_url.rstrip('/')}/markets"
        params = {"active": "true", "limit": self.settings.market_discovery_limit}

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.exception("failed to fetch polymarket gamma markets")
            return self._cache

        items = payload if isinstance(payload, list) else payload.get("markets", [])
        markets: list[VenueMarket] = []
        for item in items:
            venue_market_id = str(item.get("conditionId") or item.get("condition_id") or item.get("id") or "")
            if not venue_market_id:
                continue

            title = str(item.get("question") or item.get("title") or "").strip()
            if not title:
                continue

            outcomes = _extract_outcomes(item)
            tags = _extract_tags(item)
            category = str(item.get("category") or item.get("categorySlug") or "")

            start_time = (
                item.get("startDate")
                or item.get("startDateTime")
                or item.get("gameStartTime")
                or item.get("endDate")
            )

            market = build_venue_market(
                venue="POLY",
                venue_market_id=venue_market_id,
                title=title,
                outcomes=outcomes,
                start_time=start_time,
                category=category,
                tags=tags,
                raw=item,
            )
            markets.append(market)

        self._cache = markets
        self._last_fetch_ts = now
        logger.info("polymarket discovery completed", extra={"context": {"count": len(markets)}})
        return markets


def _extract_tags(item: dict[str, Any]) -> list[str]:
    tags = item.get("tags") or item.get("tag") or []
    values: list[str] = []

    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                value = tag.get("slug") or tag.get("label") or tag.get("name")
                if value:
                    values.append(str(value))
            elif isinstance(tag, str):
                values.append(tag)
    elif isinstance(tags, str):
        values.append(tags)

    group = item.get("groupItemTitle")
    if isinstance(group, str):
        values.append(group)

    return values


def _extract_outcomes(item: dict[str, Any]) -> list[str]:
    outcomes = item.get("outcomes")
    if outcomes is None:
        return ["YES", "NO"]

    parsed: list[str] = []
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            return ["YES", "NO"]

    if isinstance(outcomes, list):
        for outcome in outcomes:
            if isinstance(outcome, str):
                parsed.append(outcome)
            elif isinstance(outcome, dict):
                label = outcome.get("name") or outcome.get("title") or outcome.get("outcome")
                if label:
                    parsed.append(str(label))
    return parsed or ["YES", "NO"]
