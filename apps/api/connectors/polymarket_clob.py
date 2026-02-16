from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from settings import Settings

logger = logging.getLogger(__name__)

OrderbookCallback = Callable[[dict[str, Any]], Awaitable[None]]


class PolymarketClobClient:
    """
    Read-only connector for Polymarket CLOB top-of-book snapshots.
    This client intentionally does not expose order placement.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout_sec)

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_top_of_book(self, token_id: str) -> dict[str, Any] | None:
        url = f"{self.settings.poly_clob_base_url.rstrip('/')}/book"
        try:
            response = await self._client.get(url, params={"token_id": token_id})
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.debug("failed clob book fetch", extra={"context": {"token_id": token_id}})
            return None

        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        if not bids or not asks:
            return None

        best_bid = bids[0]
        best_ask = asks[0]

        try:
            bid_price = float(best_bid.get("price") or best_bid[0])
            bid_size = float(best_bid.get("size") or best_bid[1])
            ask_price = float(best_ask.get("price") or best_ask[0])
            ask_size = float(best_ask.get("size") or best_ask[1])
        except Exception:
            return None

        return {
            "venue": "POLY",
            "venue_market_id": token_id,
            "outcome": "YES",
            "best_bid": bid_price,
            "best_ask": ask_price,
            "bid_size": bid_size,
            "ask_size": ask_size,
        }

    async def poll_books(
        self,
        token_ids: list[str],
        callback: OrderbookCallback,
        *,
        interval_sec: float = 3.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        while stop_event is None or not stop_event.is_set():
            for token_id in token_ids:
                top = await self.fetch_top_of_book(token_id)
                if top:
                    await callback(top)
            await asyncio.sleep(interval_sec)
