from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

import httpx

from normalization.canonical import VenueMarket, build_venue_market
from normalization.soccer_competitions import SUPPORTED_SOCCER_COMPETITIONS
from settings import Settings

logger = logging.getLogger(__name__)

Platform = Literal["polymarket", "kalshi"]

PLATFORM_TO_VENUE: dict[str, str] = {
    "polymarket": "POLY",
    "kalshi": "KALSHI",
}

MARKET_PAGE_SIZE = 200
MARKET_CACHE_TTL_SEC = 30.0

NOISE_MARKERS = [
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


class PolyrouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout_sec)
        self._lookup_to_native: dict[tuple[str, str], str] = {}
        self._cache: dict[str, list[VenueMarket]] = {"polymarket": [], "kalshi": []}
        self._last_fetch_ts: dict[str, float] = {"polymarket": 0.0, "kalshi": 0.0}

        self._rate_lock = asyncio.Lock()
        self._last_request_ts = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def discover_markets_by_platform(self, platform: Platform, force: bool = False) -> list[VenueMarket]:
        platform_key = platform.lower().strip()
        venue = PLATFORM_TO_VENUE.get(platform_key)
        if venue is None:
            raise ValueError(f"unsupported platform: {platform}")

        now = time.time()
        if not force and self._cache[platform_key] and now - self._last_fetch_ts[platform_key] < MARKET_CACHE_TTL_SEC:
            return self._cache[platform_key]

        markets: list[VenueMarket] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _ in range(max(1, self.settings.polyrouter_market_page_limit)):
            params: dict[str, Any] = {
                "platform": platform_key,
                "limit": MARKET_PAGE_SIZE,
            }
            if cursor:
                params["cursor"] = cursor

            payload = await self._request_with_backoff("/markets", params=params)
            if payload is None:
                break

            rows, next_cursor = _rows_and_cursor(payload)
            if not rows:
                break

            for row in rows:
                market = self._normalize_market_row(platform_key, row)
                if market is None:
                    continue
                markets.append(market)
                if len(markets) >= self.settings.market_discovery_limit:
                    break

            if len(markets) >= self.settings.market_discovery_limit:
                break
            if not next_cursor or next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        self._cache[platform_key] = markets
        self._last_fetch_ts[platform_key] = now
        logger.info(
            "polyrouter discovery completed",
            extra={"context": {"platform": platform_key, "venue": venue, "count": len(markets)}},
        )
        return markets

    async def fetch_orderbooks(self, platform: Platform, market_ids: list[str]) -> list[dict[str, Any]]:
        platform_key = platform.lower().strip()
        venue = PLATFORM_TO_VENUE.get(platform_key)
        if venue is None:
            raise ValueError(f"unsupported platform: {platform}")

        deduped_ids = list(dict.fromkeys([str(market_id).strip() for market_id in market_ids if str(market_id).strip()]))
        if not deduped_ids:
            return []

        tops: list[dict[str, Any]] = []
        batch_size = max(1, self.settings.polyrouter_orderbook_batch_size)

        for index in range(0, len(deduped_ids), batch_size):
            batch = deduped_ids[index : index + batch_size]
            params = {
                "platform": platform_key,
                "market_ids": ",".join(batch),
            }
            payload = await self._request_with_backoff("/orderbooks", params=params)
            if payload is None:
                continue

            rows, _ = _rows_and_cursor(payload)
            if not rows:
                continue

            for row in rows:
                parsed = self._normalize_orderbook_row(platform_key, row)
                if parsed:
                    tops.append(parsed)

        logger.debug(
            "polyrouter orderbook fetch completed",
            extra={"context": {"platform": platform_key, "requested": len(deduped_ids), "returned": len(tops)}},
        )
        return tops

    async def _request_with_backoff(self, path: str, params: dict[str, Any]) -> Any | None:
        url = f"{self.settings.polyrouter_base_url.rstrip('/')}/{path.lstrip('/')}"
        headers: dict[str, str] = {}
        if self.settings.polyrouter_api_key:
            headers["X-API-Key"] = self.settings.polyrouter_api_key

        for attempt in range(4):
            await self._respect_rate_limit()
            try:
                response = await self._client.get(url, params=params, headers=headers)
                if response.status_code == 429:
                    await asyncio.sleep(0.6 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except Exception:
                if attempt == 3:
                    logger.exception("polyrouter request failed", extra={"context": {"path": path, "params": params}})
                    return None
                await asyncio.sleep(0.4 * (attempt + 1))
        return None

    async def _respect_rate_limit(self) -> None:
        req_per_min = max(1, min(self.settings.polyrouter_req_per_min, 1_000))
        min_interval = 60.0 / float(req_per_min)
        async with self._rate_lock:
            now = time.monotonic()
            delta = now - self._last_request_ts
            if self._last_request_ts and delta < min_interval:
                await asyncio.sleep(min_interval - delta)
            self._last_request_ts = time.monotonic()

    def _normalize_market_row(self, platform: str, row: Any) -> VenueMarket | None:
        if not isinstance(row, dict):
            return None

        venue = PLATFORM_TO_VENUE[platform]
        lookup_id = _extract_market_lookup_id(row)
        if not lookup_id:
            return None

        venue_market_id = _extract_native_market_id(platform, row, fallback=lookup_id)
        title = _first_string(
            row.get("title"),
            row.get("question"),
            row.get("name"),
            row.get("event_title"),
            row.get("eventTitle"),
        )
        if not title:
            return None

        outcomes = _extract_outcomes(row)
        question = _first_string(row.get("question"), title) or title
        if not _is_winner_market(question, outcomes):
            return None

        has_draw = _has_draw(row, outcomes, question)
        if has_draw:
            outcomes = ["HOME", "DRAW", "AWAY"]

        start_time = _first_value(
            row.get("start_time"),
            row.get("startTime"),
            row.get("event_start_time"),
            row.get("eventStartTime"),
            row.get("game_start_time"),
            row.get("gameStartTime"),
            row.get("end_time"),
            row.get("endTime"),
            row.get("expiration_time"),
            row.get("expirationTime"),
        )

        tags = _extract_tags(row)
        sport_hint, competition_hint = _extract_sport_and_competition(row, title, tags)
        if sport_hint is None:
            return None

        raw: dict[str, Any] = dict(row)
        raw["polyrouter_platform"] = platform
        raw["polyrouter_lookup_id"] = lookup_id
        raw["polyrouter_market_id"] = lookup_id
        raw["polyrouter_native_market_id"] = venue_market_id

        yes_bid = _coerce_price(
            _first_value(
                row.get("yes_bid"),
                row.get("yesBid"),
                row.get("best_bid"),
                row.get("bestBid"),
                row.get("bid"),
                row.get("price_bid"),
                row.get("bid_price"),
            )
        )
        yes_ask = _coerce_price(
            _first_value(
                row.get("yes_ask"),
                row.get("yesAsk"),
                row.get("best_ask"),
                row.get("bestAsk"),
                row.get("ask"),
                row.get("price_ask"),
                row.get("ask_price"),
            )
        )
        yes_bid_size = _coerce_size(
            _first_value(
                row.get("yes_bid_size"),
                row.get("yesBidSize"),
                row.get("bid_size"),
                row.get("best_bid_size"),
                row.get("size_bid"),
            )
        )
        yes_ask_size = _coerce_size(
            _first_value(
                row.get("yes_ask_size"),
                row.get("yesAskSize"),
                row.get("ask_size"),
                row.get("best_ask_size"),
                row.get("size_ask"),
            )
        )
        no_bid = _coerce_price(_first_value(row.get("no_bid"), row.get("noBid")))
        no_ask = _coerce_price(_first_value(row.get("no_ask"), row.get("noAsk")))

        if yes_bid is not None:
            raw["yes_bid"] = yes_bid
        if yes_ask is not None:
            raw["yes_ask"] = yes_ask
        if yes_bid_size is not None:
            raw["yes_bid_size"] = yes_bid_size
        if yes_ask_size is not None:
            raw["yes_ask_size"] = yes_ask_size
        if no_bid is not None:
            raw["no_bid"] = no_bid
        if no_ask is not None:
            raw["no_ask"] = no_ask

        market = build_venue_market(
            venue=venue,
            venue_market_id=venue_market_id,
            title=title,
            outcomes=outcomes,
            start_time=start_time,
            sport_hint=sport_hint,
            competition_hint=competition_hint,
            category="sports",
            tags=tags,
            raw=raw,
        )
        market.market_type = "WINNER_3WAY" if has_draw else "WINNER_BINARY"

        if not _is_supported_scope(market):
            return None

        self._lookup_to_native[(platform, lookup_id)] = venue_market_id
        return market

    def _normalize_orderbook_row(self, platform: str, row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None

        venue = PLATFORM_TO_VENUE[platform]

        lookup_id = _extract_market_lookup_id(row)
        native_market_id = _extract_native_market_id(platform, row, fallback="")

        mapped_native = self._lookup_to_native.get((platform, lookup_id), "") if lookup_id else ""
        if mapped_native and (not native_market_id or native_market_id == lookup_id):
            native_market_id = mapped_native
        if not native_market_id and lookup_id:
            native_market_id = lookup_id
        if not native_market_id:
            return None

        bid_price = _coerce_price(
            _first_value(
                row.get("yes_bid"),
                row.get("yesBid"),
                row.get("best_bid"),
                row.get("bestBid"),
                row.get("bid"),
                row.get("bid_price"),
            )
        )
        ask_price = _coerce_price(
            _first_value(
                row.get("yes_ask"),
                row.get("yesAsk"),
                row.get("best_ask"),
                row.get("bestAsk"),
                row.get("ask"),
                row.get("ask_price"),
            )
        )
        bid_size = _coerce_size(
            _first_value(
                row.get("yes_bid_size"),
                row.get("yesBidSize"),
                row.get("bid_size"),
                row.get("best_bid_size"),
            )
        )
        ask_size = _coerce_size(
            _first_value(
                row.get("yes_ask_size"),
                row.get("yesAskSize"),
                row.get("ask_size"),
                row.get("best_ask_size"),
            )
        )

        if bid_price is None or ask_price is None:
            bids = row.get("bids") if isinstance(row.get("bids"), list) else []
            asks = row.get("asks") if isinstance(row.get("asks"), list) else []
            if bids and asks:
                best_bid = bids[0]
                best_ask = asks[0]
                bid_price = bid_price if bid_price is not None else _coerce_price(_book_level_value(best_bid, "price", 0))
                ask_price = ask_price if ask_price is not None else _coerce_price(_book_level_value(best_ask, "price", 0))
                bid_size = bid_size if bid_size is not None else _coerce_size(_book_level_value(best_bid, "size", 1))
                ask_size = ask_size if ask_size is not None else _coerce_size(_book_level_value(best_ask, "size", 1))

        if bid_price is None or ask_price is None:
            return None

        return {
            "venue": venue,
            "venue_market_id": native_market_id,
            "outcome": "YES",
            "best_bid": bid_price,
            "best_ask": ask_price,
            "bid_size": bid_size or 0.0,
            "ask_size": ask_size or 0.0,
        }


def _rows_and_cursor(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], None
    if not isinstance(payload, dict):
        return [], None

    rows = _first_value(
        payload.get("data"),
        payload.get("markets"),
        payload.get("orderbooks"),
        payload.get("items"),
        payload.get("results"),
    )
    if isinstance(rows, dict):
        rows = _first_value(rows.get("items"), rows.get("results"), rows.get("data"))
    parsed_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    cursor = _first_string(payload.get("next_cursor"), payload.get("nextCursor"), payload.get("cursor"))
    return parsed_rows, cursor


def _extract_tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for value in (
        row.get("tags"),
        row.get("tag"),
        row.get("league"),
        row.get("competition"),
        row.get("series"),
        row.get("category"),
        row.get("sport"),
        row.get("slug"),
        row.get("event_slug"),
        row.get("eventSlug"),
    ):
        if isinstance(value, str):
            tags.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    tags.append(item)
                elif isinstance(item, dict):
                    label = _first_string(item.get("slug"), item.get("name"), item.get("title"), item.get("label"))
                    if label:
                        tags.append(label)
    return tags


def _extract_sport_and_competition(
    row: dict[str, Any],
    title: str,
    tags: list[str],
) -> tuple[str | None, str | None]:
    values: list[str] = [title.lower()]
    values.extend(tag.lower() for tag in tags)

    for key in (
        "sport",
        "league",
        "competition",
        "series",
        "category",
        "event_title",
        "eventTitle",
        "slug",
        "event_slug",
        "eventSlug",
    ):
        value = row.get(key)
        if isinstance(value, str):
            values.append(value.lower())

    joined = " ".join(values)
    has_nba = "nba" in joined or "basketball" in joined

    competition: str | None = None
    if "epl" in joined or "premier league" in joined:
        competition = "EPL"
    elif "ucl" in joined or "champions league" in joined:
        competition = "UCL"
    elif "uel" in joined or "europa league" in joined:
        competition = "UEL"
    elif "laliga" in joined or "la liga" in joined:
        competition = "LALIGA"

    if has_nba:
        return "NBA", "NBA"
    if competition:
        return "SOCCER", competition
    if "soccer" in joined or "football" in joined:
        return "SOCCER", None
    return None, None


def _extract_market_lookup_id(row: dict[str, Any]) -> str:
    return _first_string(
        row.get("market_id"),
        row.get("marketId"),
        row.get("id"),
        row.get("uuid"),
        row.get("condition_id"),
        row.get("conditionId"),
        row.get("ticker"),
        row.get("market_ticker"),
        row.get("marketTicker"),
    ) or ""


def _extract_native_market_id(platform: str, row: dict[str, Any], fallback: str) -> str:
    if platform == "polymarket":
        return (
            _first_string(
                row.get("condition_id"),
                row.get("conditionId"),
                row.get("clob_token_id"),
                row.get("clobTokenId"),
                row.get("token_id"),
                row.get("tokenId"),
                row.get("market_id"),
                row.get("marketId"),
                row.get("id"),
            )
            or fallback
        )

    return (
        _first_string(
            row.get("ticker"),
            row.get("market_ticker"),
            row.get("marketTicker"),
            row.get("event_ticker"),
            row.get("eventTicker"),
            row.get("market_id"),
            row.get("marketId"),
            row.get("id"),
        )
        or fallback
    )


def _extract_outcomes(row: dict[str, Any]) -> list[str]:
    outcomes = _first_value(row.get("outcomes"), row.get("market_outcomes"), row.get("tokens"))
    if outcomes is None:
        return ["YES", "NO"]

    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            return ["YES", "NO"]

    parsed: list[str] = []
    if isinstance(outcomes, list):
        for outcome in outcomes:
            if isinstance(outcome, str):
                parsed.append(outcome)
                continue
            if isinstance(outcome, dict):
                label = _first_string(
                    outcome.get("name"),
                    outcome.get("title"),
                    outcome.get("label"),
                    outcome.get("outcome"),
                    outcome.get("token"),
                )
                if label:
                    parsed.append(label)

    return parsed or ["YES", "NO"]


def _has_draw(row: dict[str, Any], outcomes: list[str], question: str) -> bool:
    lowered_outcomes = {str(outcome).strip().lower() for outcome in outcomes}
    if "draw" in lowered_outcomes or "tie" in lowered_outcomes:
        return True
    for key in ("yes_sub_title", "subtitle", "title", "question"):
        value = row.get(key)
        if isinstance(value, str) and ("draw" in value.lower() or "tie" in value.lower()):
            return True
    return "draw" in question.lower() or "tie" in question.lower()


def _is_winner_market(question: str, outcomes: list[str]) -> bool:
    q = question.lower().strip()
    if any(marker in q for marker in NOISE_MARKERS):
        return False

    if "end in a draw" in q:
        return True
    if " winner" in q or q.endswith("winner?"):
        return True
    if " win on " in q:
        return True
    if len(outcomes) == 2 and (" vs" in q or " at " in q):
        lowered_outcomes = {str(outcome).strip().lower() for outcome in outcomes}
        if lowered_outcomes not in ({"yes", "no"}, {"over", "under"}):
            return True
    return " win " in q and q.startswith("will ")


def _is_supported_scope(market: VenueMarket) -> bool:
    if market.sport == "NBA":
        return market.competition == "NBA"
    if market.sport == "SOCCER":
        return market.competition in SUPPORTED_SOCCER_COMPETITIONS
    return False


def _book_level_value(level: Any, key: str, index: int) -> Any:
    if isinstance(level, dict):
        return level.get(key)
    if isinstance(level, (list, tuple)) and len(level) > index:
        return level[index]
    return None


def _coerce_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed > 1.0:
        parsed = parsed / 100.0
    if 0.0 <= parsed <= 1.0:
        return parsed
    return None


def _coerce_size(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            parsed = value.strip()
            if parsed:
                return parsed
    return None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
