from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from settings import Settings

logger = logging.getLogger(__name__)

OrderbookCallback = Callable[[dict[str, Any]], Awaitable[None]]


class KalshiWsClient:
    """
    Read-only websocket connector for Kalshi market updates.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_orderbooks(
        self,
        tickers: list[str],
        callback: OrderbookCallback,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        if not tickers:
            return

        backoff = 1.0
        while stop_event is None or not stop_event.is_set():
            try:
                async with websockets.connect(self.settings.kalshi_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    subscribe_msg = {
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["orderbook_delta"],
                            "market_tickers": tickers,
                        },
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    backoff = 1.0

                    while stop_event is None or not stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        payload = json.loads(raw)
                        parsed = _parse_orderbook_payload(payload)
                        if parsed:
                            await callback(parsed)
            except Exception:
                logger.warning(
                    "kalshi ws reconnect",
                    extra={"context": {"sleep_sec": round(backoff, 2), "tickers": len(tickers)}},
                )
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 1.6)


def _parse_orderbook_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    msg = payload.get("msg") or payload
    market_ticker = msg.get("market_ticker") or msg.get("ticker")
    yes_bid = msg.get("yes_bid")
    yes_ask = msg.get("yes_ask")
    yes_bid_size = msg.get("yes_bid_size") or msg.get("bid_size")
    yes_ask_size = msg.get("yes_ask_size") or msg.get("ask_size")

    if market_ticker is None or yes_bid is None or yes_ask is None:
        return None

    try:
        return {
            "venue": "KALSHI",
            "venue_market_id": str(market_ticker),
            "outcome": "YES",
            "best_bid": float(yes_bid) / 100.0 if float(yes_bid) > 1.0 else float(yes_bid),
            "best_ask": float(yes_ask) / 100.0 if float(yes_ask) > 1.0 else float(yes_ask),
            "bid_size": float(yes_bid_size or 0.0),
            "ask_size": float(yes_ask_size or 0.0),
        }
    except (TypeError, ValueError):
        return None
