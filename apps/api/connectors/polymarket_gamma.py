from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

from normalization.canonical import VenueMarket, build_venue_market
from settings import Settings

logger = logging.getLogger(__name__)

EVENT_PAGE_SIZE = 200
EVENT_PAGE_CAP = 30
GAME_SLUG_PATTERNS: list[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"^nba-[a-z0-9-]+-\d{4}-\d{2}-\d{2}$"), ("NBA", "NBA")),
    (re.compile(r"^epl-[a-z0-9-]+-\d{4}-\d{2}-\d{2}$"), ("SOCCER", "EPL")),
    (re.compile(r"^ucl-[a-z0-9-]+-\d{4}-\d{2}-\d{2}$"), ("SOCCER", "UCL")),
    (re.compile(r"^uel-[a-z0-9-]+-\d{4}-\d{2}-\d{2}$"), ("SOCCER", "UEL")),
    (re.compile(r"^lal-[a-z0-9-]+-\d{4}-\d{2}-\d{2}$"), ("SOCCER", "LALIGA")),
]


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

        events = await self._fetch_sports_events()
        if not events:
            logger.warning("polymarket discovery returned no sports events")
            return self._cache

        markets: list[VenueMarket] = []
        for event in events:
            event_slug = str(event.get("slug") or "").lower().strip()
            event_title = str(event.get("title") or "").strip()
            if not event_slug or not event_title or "more-markets" in event_slug:
                continue

            sport_comp = _competition_from_event_slug(event_slug)
            if sport_comp is None:
                continue
            sport_hint, competition_hint = sport_comp

            if sport_hint == "NBA" and not self.settings.enable_nba:
                continue
            if sport_hint == "SOCCER" and not self.settings.enable_soccer:
                continue

            event_markets = event.get("markets") or []
            if not isinstance(event_markets, list):
                continue

            has_draw = _event_has_draw(event_markets)
            for item in event_markets:
                venue_market_id = str(item.get("conditionId") or item.get("condition_id") or item.get("id") or "").strip()
                if not venue_market_id:
                    continue

                if item.get("closed") is True:
                    continue

                question = str(item.get("question") or item.get("title") or "").strip()
                if not question:
                    continue

                outcomes = _extract_outcomes(item)
                if not _is_winner_market(question, outcomes):
                    continue

                if has_draw:
                    outcomes = ["HOME", "DRAW", "AWAY"]

                # Prioritize game-aligned timestamps.
                start_time = (
                    item.get("endDate")
                    or item.get("gameStartTime")
                    or event.get("endDate")
                    or item.get("startDate")
                    or event.get("startDate")
                )

                tags = _extract_tags(item)
                tags.extend([event_slug, sport_hint, competition_hint, question])

                market = build_venue_market(
                    venue="POLY",
                    venue_market_id=venue_market_id,
                    title=event_title,
                    outcomes=outcomes,
                    start_time=start_time,
                    sport_hint=sport_hint,
                    competition_hint=competition_hint,
                    category="sports",
                    tags=tags,
                    raw={"event": event, **item},
                )

                if has_draw:
                    market.market_type = "WINNER_3WAY"
                else:
                    market.market_type = "WINNER_BINARY"

                markets.append(market)
                if len(markets) >= self.settings.market_discovery_limit:
                    break
            if len(markets) >= self.settings.market_discovery_limit:
                break

        self._cache = markets
        self._last_fetch_ts = now
        logger.info("polymarket discovery completed", extra={"context": {"count": len(markets), "events": len(events)}})
        return markets

    async def _fetch_sports_events(self) -> list[dict[str, Any]]:
        url = f"{self.settings.poly_gamma_base_url.rstrip('/')}/events"
        events: list[dict[str, Any]] = []

        for page in range(EVENT_PAGE_CAP):
            offset = page * EVENT_PAGE_SIZE
            params = {
                "tag_slug": "sports",
                "closed": "false",
                "limit": EVENT_PAGE_SIZE,
                "offset": offset,
            }

            payload = await self._request_with_backoff(url, params)
            if payload is None:
                break

            rows = payload if isinstance(payload, list) else payload.get("events") or payload.get("data") or []
            if not isinstance(rows, list) or not rows:
                break

            events.extend(rows)
            if len(rows) < EVENT_PAGE_SIZE:
                break

        return events

    async def _request_with_backoff(self, url: str, params: dict[str, Any]) -> Any | None:
        for attempt in range(4):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(0.7 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except Exception:
                if attempt == 3:
                    logger.exception("polymarket request failed", extra={"context": {"params": params}})
                    return None
                await asyncio.sleep(0.4 * (attempt + 1))
        return None


def _competition_from_event_slug(slug: str) -> tuple[str, str] | None:
    for pattern, sport_comp in GAME_SLUG_PATTERNS:
        if pattern.match(slug):
            return sport_comp
    return None


def _is_winner_market(question: str, outcomes: list[str]) -> bool:
    q = question.lower().strip()

    # Exclude spread/props/totals markets.
    noise_markers = [
        "spread",
        "o/u",
        "over ",
        "under ",
        "assists",
        "points",
        "rebounds",
        "threes",
        "3-pointers",
        "turnovers",
        "steals",
        "blocks",
        "1h",
        "first half",
        "double-double",
        "triple-double",
        "margins",
        "by more than",
        "by at least",
    ]
    if any(marker in q for marker in noise_markers):
        return False

    if "end in a draw" in q:
        return True
    if " winner" in q or q.endswith("winner?"):
        return True
    if " win on " in q:
        return True

    # Team-vs-team head-to-head moneyline market style.
    if len(outcomes) == 2 and (" vs" in q or " at " in q):
        lowered_outcomes = [str(out).strip().lower() for out in outcomes]
        if set(lowered_outcomes) != {"yes", "no"} and set(lowered_outcomes) != {"over", "under"}:
            return True

    return " win " in q and q.startswith("will ")


def _event_has_draw(event_markets: list[dict[str, Any]]) -> bool:
    for item in event_markets:
        question = str(item.get("question") or item.get("title") or "").lower()
        if "draw" in question or "tie" in question:
            return True
    return False


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
