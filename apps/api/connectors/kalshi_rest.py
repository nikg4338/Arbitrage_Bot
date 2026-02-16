from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from normalization.canonical import VenueMarket, build_venue_market, parse_time
from settings import Settings

logger = logging.getLogger(__name__)

SERIES_TO_COMPETITION: dict[str, tuple[str, str]] = {
    "KXNBAGAME": ("NBA", "NBA"),
    "KXEPLGAME": ("SOCCER", "EPL"),
    "KXUCLGAME": ("SOCCER", "UCL"),
    "KXUELGAME": ("SOCCER", "UEL"),
    "KXLALIGAGAME": ("SOCCER", "LALIGA"),
}
DATE_TOKEN_RE = re.compile(r"-(\d{2}[A-Z]{3}\d{2})")


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

        raw_items: dict[str, dict[str, Any]] = {}
        for series_ticker, (sport, _) in SERIES_TO_COMPETITION.items():
            if sport == "NBA" and not self.settings.enable_nba:
                continue
            if sport == "SOCCER" and not self.settings.enable_soccer:
                continue

            pages = await self._fetch_series(series_ticker)
            for row in pages:
                ticker = str(row.get("ticker") or row.get("market_ticker") or "").strip()
                if ticker:
                    raw_items[ticker] = row

        if not raw_items:
            logger.warning("kalshi discovery returned no game-feed markets")
            return self._cache

        event_to_tickers: dict[str, list[str]] = defaultdict(list)
        for row in raw_items.values():
            event_ticker = str(row.get("event_ticker") or "").strip()
            if event_ticker:
                event_to_tickers[event_ticker].append(str(row.get("ticker") or ""))

        markets: list[VenueMarket] = []
        for row in raw_items.values():
            ticker = str(row.get("ticker") or row.get("market_ticker") or "").strip()
            base_title = str(row.get("title") or row.get("subtitle") or "").strip()
            if not ticker or not base_title:
                continue

            series_ticker = (
                str(row.get("series_ticker") or "").strip().upper()
                or str(row.get("event_ticker") or "").split("-")[0].upper()
                or str(row.get("ticker") or "").split("-")[0].upper()
            )
            sport_hint, competition_hint = SERIES_TO_COMPETITION.get(series_ticker, (None, None))
            if sport_hint is None:
                continue

            # Keep only game winner markets from these feeds.
            if "winner" not in base_title.lower():
                continue

            event_ticker = str(row.get("event_ticker") or "").strip()
            has_draw = _event_has_draw(row, event_to_tickers.get(event_ticker, []))
            outcome_label = _outcome_label(row)

            title = base_title

            start_time = _derive_game_time(row)

            tags = [
                series_ticker,
                event_ticker,
                str(row.get("category") or ""),
                outcome_label,
            ]
            tags = [tag for tag in tags if tag]

            outcomes = ["HOME", "DRAW", "AWAY"] if has_draw else ["YES", "NO"]
            market = build_venue_market(
                venue="KALSHI",
                venue_market_id=ticker,
                title=title,
                outcomes=outcomes,
                start_time=start_time,
                sport_hint=sport_hint,
                competition_hint=competition_hint,
                category=str(row.get("category") or ""),
                tags=tags,
                raw=row,
            )
            market.market_type = "WINNER_3WAY" if has_draw else "WINNER_BINARY"
            markets.append(market)

        self._cache = markets
        self._last_fetch_ts = now
        logger.info("kalshi discovery completed", extra={"context": {"count": len(markets)}})
        return markets

    async def _fetch_series(self, series_ticker: str) -> list[dict[str, Any]]:
        url = f"{self.settings.kalshi_rest_base_url.rstrip('/')}/markets"
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = {
                "status": "open",
                "series_ticker": series_ticker,
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor

            payload = await self._request_with_backoff(url, params)
            if payload is None:
                break

            page_items = payload.get("markets") if isinstance(payload, dict) else payload
            if not isinstance(page_items, list) or not page_items:
                break

            items.extend(page_items)

            next_cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

            if len(items) >= max(200, self.settings.market_discovery_limit):
                break

        return items

    async def _request_with_backoff(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in range(4):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(0.6 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except Exception:
                if attempt == 3:
                    logger.exception("kalshi request failed", extra={"context": {"params": params}})
                    return None
                await asyncio.sleep(0.4 * (attempt + 1))
        return None


def _derive_game_time(item: dict[str, Any]) -> datetime | str | None:
    ticker = str(item.get("event_ticker") or item.get("ticker") or "").upper()
    date_token_match = DATE_TOKEN_RE.search(ticker)

    reference_dt = (
        parse_time(item.get("event_start_time"))
        or parse_time(item.get("close_time"))
        or parse_time(item.get("expiration_time"))
        or parse_time(item.get("latest_expiration_time"))
        or parse_time(item.get("open_time"))
    )

    if not date_token_match:
        return reference_dt

    try:
        date_part = datetime.strptime(date_token_match.group(1), "%y%b%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return reference_dt

    if reference_dt:
        derived = datetime(
            year=date_part.year,
            month=date_part.month,
            day=date_part.day,
            hour=reference_dt.hour,
            minute=reference_dt.minute,
            second=reference_dt.second,
            tzinfo=timezone.utc,
        )

        # NBA tickers use local game date; convert evening US games to next-day UTC.
        event_ticker = str(item.get("event_ticker") or item.get("ticker") or "").upper()
        if event_ticker.startswith("KXNBAGAME") and derived.hour <= 8:
            from datetime import timedelta

            derived = derived + timedelta(days=1)
        return derived

    return date_part


def _event_has_draw(item: dict[str, Any], sibling_tickers: list[str]) -> bool:
    ticker = str(item.get("ticker") or "").upper()
    yes_sub_title = str(item.get("yes_sub_title") or "").lower()
    subtitle = str(item.get("subtitle") or "").lower()

    if ticker.endswith("-TIE"):
        return True
    if "draw" in yes_sub_title or "tie" in yes_sub_title:
        return True
    if "draw" in subtitle or "tie" in subtitle:
        return True
    return any(str(s).upper().endswith("-TIE") for s in sibling_tickers)


def _outcome_label(item: dict[str, Any]) -> str:
    yes_sub_title = str(item.get("yes_sub_title") or "").strip()
    if yes_sub_title:
        return yes_sub_title

    ticker = str(item.get("ticker") or "")
    if "-" in ticker:
        return ticker.split("-")[-1]
    return ""
