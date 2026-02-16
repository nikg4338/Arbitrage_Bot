from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import WebSocket
from sqlalchemy.dialects.sqlite import insert

from connectors.kalshi_rest import KalshiRestClient
from connectors.kalshi_ws import KalshiWsClient
from connectors.polymarket_clob import PolymarketClobClient
from connectors.polymarket_gamma import PolymarketGammaClient
from connectors.polyrouter import PolyrouterClient
from db import session_scope
from engine.orderbook import OrderBookService
from engine.signaler import refresh_signals
from models import CanonicalEvent, MarketBinding, MispricingSignal, OrderBookTop, PortfolioSnapshot
from normalization.canonical import VenueMarket, build_venue_market
from normalization.resolver import load_overrides, resolve_markets
from paper.portfolio import auto_close_started_events, mark_to_market
from settings import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectorHealth:
    name: str
    ok: bool = False
    last_ok: str | None = None
    last_error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class SignalHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            current = list(self._connections)

        stale: list[WebSocket] = []
        for websocket in current:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.discard(websocket)


class AppScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gamma = PolymarketGammaClient(settings)
        self.poly_clob = PolymarketClobClient(settings)
        self.kalshi_rest = KalshiRestClient(settings)
        self.kalshi_ws = KalshiWsClient(settings)
        self.polyrouter = PolyrouterClient(settings)

        self.hub = SignalHub()
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._demo_rows_purged = False
        self._last_snapshot: dict[str, Any] = {
            "type": "snapshot",
            "data_source": self._active_market_data_source(),
            "signals": [],
            "orderbooks": [],
        }

        self.health = {
            "gamma": ConnectorHealth(name="gamma"),
            "kalshi_rest": ConnectorHealth(name="kalshi_rest"),
            "poly_clob": ConnectorHealth(name="poly_clob"),
            "kalshi_ws": ConnectorHealth(name="kalshi_ws"),
            "polyrouter": ConnectorHealth(name="polyrouter"),
        }

    async def start(self) -> None:
        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(self._discovery_loop(), name="discovery-loop"),
            asyncio.create_task(self._signal_loop(), name="signal-loop"),
            asyncio.create_task(self._broadcast_loop(), name="broadcast-loop"),
        ]

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.gamma.close()
        await self.kalshi_rest.close()
        await self.poly_clob.close()
        await self.polyrouter.close()

    def health_payload(self) -> dict[str, Any]:
        connectors = {
            name: {
                "ok": row.ok,
                "last_ok": row.last_ok,
                "last_error": row.last_error,
                "detail": row.detail,
            }
            for name, row in self.health.items()
        }
        return {
            "active_data_source": self._active_market_data_source(),
            "configured_data_source": str(self.settings.market_data_source).strip().lower(),
            "connectors": connectors,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        return self._last_snapshot

    async def _discovery_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._run_discovery_cycle()
            except Exception:
                logger.exception("discovery cycle failed")
            await asyncio.sleep(self.settings.discovery_interval_sec)

    async def _run_discovery_cycle(self) -> None:
        if not self.settings.enable_demo_fallback and not self._demo_rows_purged:
            self._purge_demo_data()
            self._demo_rows_purged = True

        source = self._active_market_data_source()
        poly_markets, kalshi_markets = await self._discover_markets_from_source(source)

        poly_markets = self._apply_sport_toggles(poly_markets)
        kalshi_markets = self._apply_sport_toggles(kalshi_markets)

        if not poly_markets or not kalshi_markets:
            if self.settings.enable_demo_fallback:
                poly_markets, kalshi_markets = self._demo_markets()
            else:
                logger.warning(
                    "discovery returned insufficient live markets; demo fallback disabled",
                    extra={
                        "context": {
                            "source": source,
                            "poly_markets": len(poly_markets),
                            "kalshi_markets": len(kalshi_markets),
                        }
                    },
                )
                return

        overrides = load_overrides(self.settings.overrides_path)
        pairs = resolve_markets(poly_markets, kalshi_markets, overrides=overrides)

        with session_scope() as session:
            for pair in pairs:
                self._upsert_event(session, pair)
                self._upsert_binding(session, pair, venue="POLY")
                self._upsert_binding(session, pair, venue="KALSHI")

            for market in poly_markets + kalshi_markets:
                self._seed_orderbook_from_market(session, market)

        if source == "polyrouter":
            await self._refresh_polyrouter_books(pairs)
        else:
            # Best-effort snapshot pulls for resolved Polymarket markets.
            await self._refresh_poly_books([pair.poly.venue_market_id for pair in pairs])

    async def _signal_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with session_scope() as session:
                    refresh_signals(session, self.settings)
                    auto_close_started_events(session)
                    mark_to_market(session)
            except Exception:
                logger.exception("signal cycle failed")
            await asyncio.sleep(self.settings.signal_interval_sec)

    async def _broadcast_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload = self._build_snapshot()
                self._last_snapshot = payload
                await self.hub.broadcast(payload)
            except Exception:
                logger.exception("broadcast loop failed")
            await asyncio.sleep(self.settings.ws_broadcast_interval_sec)

    def _build_snapshot(self) -> dict[str, Any]:
        with session_scope() as session:
            signals_query = session.query(MispricingSignal).filter(MispricingSignal.status == "OPEN")
            if not self.settings.enable_demo_fallback:
                signals_query = signals_query.filter(
                    ~MispricingSignal.buy_market_id.like("%demo%"),
                    ~MispricingSignal.sell_market_id.like("%demo%"),
                )

            signals = (
                signals_query
                .order_by(MispricingSignal.edge_after_costs.desc())
                .limit(100)
                .all()
            )

            events = {
                row.id: row
                for row in session.query(CanonicalEvent)
                .filter(CanonicalEvent.id.in_([signal.canonical_event_id for signal in signals]))
                .all()
            }

            orderbook_query = session.query(OrderBookTop)
            if not self.settings.enable_demo_fallback:
                orderbook_query = orderbook_query.filter(~OrderBookTop.venue_market_id.like("%demo%"))

            orderbooks = (
                orderbook_query
                .order_by(OrderBookTop.ts.desc())
                .limit(200)
                .all()
            )

            snapshots = (
                session.query(PortfolioSnapshot)
                .order_by(PortfolioSnapshot.ts.desc())
                .limit(100)
                .all()
            )

            rows: list[dict[str, Any]] = []
            for signal in signals:
                event = events.get(signal.canonical_event_id)
                rows.append(
                    {
                        "id": signal.id,
                        "canonical_event_id": signal.canonical_event_id,
                        "sport": event.sport if event else None,
                        "competition": event.competition if event else None,
                        "match": event.title_canonical if event else signal.canonical_event_id,
                        "start_time_utc": event.start_time_utc.isoformat() if event else None,
                        "outcome": signal.outcome,
                        "buy_venue": signal.buy_venue,
                        "sell_venue": signal.sell_venue,
                        "buy_market_id": signal.buy_market_id,
                        "sell_market_id": signal.sell_market_id,
                        "buy_price": signal.buy_price,
                        "sell_price": signal.sell_price,
                        "size_suggested": signal.size_suggested,
                        "edge_raw": signal.edge_raw,
                        "edge_after_costs": signal.edge_after_costs,
                        "confidence": signal.confidence,
                        "status": signal.status,
                        "created_at": signal.created_at.isoformat(),
                    }
                )

            return {
                "type": "snapshot",
                "ts": datetime.now(timezone.utc).isoformat(),
                "data_source": self._active_market_data_source(),
                "signals": rows,
                "orderbooks": [
                    {
                        "venue": row.venue,
                        "venue_market_id": row.venue_market_id,
                        "outcome": row.outcome,
                        "best_bid": row.best_bid,
                        "best_ask": row.best_ask,
                        "bid_size": row.bid_size,
                        "ask_size": row.ask_size,
                        "ts": row.ts.isoformat(),
                    }
                    for row in orderbooks
                ],
                "equity_curve": [
                    {
                        "ts": row.ts.isoformat(),
                        "equity": row.equity,
                        "realized": row.realized_pnl,
                        "unrealized": row.unrealized_pnl,
                    }
                    for row in reversed(snapshots)
                ],
            }

    def _purge_demo_data(self) -> None:
        with session_scope() as session:
            session.query(MispricingSignal).filter(
                MispricingSignal.buy_market_id.like("%demo%") | MispricingSignal.sell_market_id.like("%demo%")
            ).delete(synchronize_session=False)

            session.query(OrderBookTop).filter(OrderBookTop.venue_market_id.like("%demo%")).delete(synchronize_session=False)
            session.query(MarketBinding).filter(MarketBinding.venue_market_id.like("%demo%")).delete(synchronize_session=False)

            bound_event_ids = session.query(MarketBinding.canonical_event_id).distinct()
            session.query(CanonicalEvent).filter(~CanonicalEvent.id.in_(bound_event_ids)).delete(synchronize_session=False)

    async def _discover_markets_from_source(self, source: str) -> tuple[list[VenueMarket], list[VenueMarket]]:
        if source == "polyrouter":
            poly_markets = await self.polyrouter.discover_markets_by_platform("polymarket")
            kalshi_markets = await self.polyrouter.discover_markets_by_platform("kalshi")

            self._mark_health(
                "polyrouter",
                ok=bool(poly_markets or kalshi_markets),
                detail={
                    "source": "polyrouter",
                    "poly_markets": len(poly_markets),
                    "kalshi_markets": len(kalshi_markets),
                },
            )
            self._mark_health("gamma", ok=False, detail={"active": False, "source": "polyrouter"})
            self._mark_health("kalshi_rest", ok=False, detail={"active": False, "source": "polyrouter"})
            self._mark_health("poly_clob", ok=False, detail={"active": False, "source": "polyrouter"})
            return poly_markets, kalshi_markets

        poly_markets = await self.gamma.discover_markets()
        kalshi_markets = await self.kalshi_rest.discover_markets()

        polyrouter_ready = self.settings.polyrouter_enable and bool(self.settings.polyrouter_api_key)
        self._mark_health("gamma", ok=bool(poly_markets), detail={"source": "direct", "markets": len(poly_markets)})
        self._mark_health("kalshi_rest", ok=bool(kalshi_markets), detail={"source": "direct", "markets": len(kalshi_markets)})
        self._mark_health("polyrouter", ok=False, detail={"active": False, "configured": polyrouter_ready, "source": "direct"})
        return poly_markets, kalshi_markets

    async def _refresh_poly_books(self, market_ids: list[str]) -> None:
        if not market_ids:
            return

        ok = False
        for market_id in market_ids[:100]:
            top = await self.poly_clob.fetch_top_of_book(market_id)
            if not top:
                continue
            ok = True
            with session_scope() as session:
                OrderBookService.upsert_top(
                    session,
                    venue=top["venue"],
                    venue_market_id=top["venue_market_id"],
                    outcome=top["outcome"],
                    best_bid=top["best_bid"],
                    best_ask=top["best_ask"],
                    bid_size=top["bid_size"],
                    ask_size=top["ask_size"],
                )
        self._mark_health("poly_clob", ok=ok, detail={"requested": len(market_ids)})

    async def _refresh_polyrouter_books(self, pairs: list[Any]) -> None:
        if not pairs:
            self._mark_health("polyrouter", ok=False, detail={"source": "polyrouter", "requested": 0, "updated": 0})
            return

        poly_lookup_ids = [
            str(pair.poly.raw.get("polyrouter_lookup_id") or pair.poly.venue_market_id)
            for pair in pairs
            if getattr(pair, "poly", None) is not None
        ]
        kalshi_lookup_ids = [
            str(pair.kalshi.raw.get("polyrouter_lookup_id") or pair.kalshi.venue_market_id)
            for pair in pairs
            if getattr(pair, "kalshi", None) is not None
        ]

        tops: list[dict[str, Any]] = []
        if poly_lookup_ids:
            tops.extend(await self.polyrouter.fetch_orderbooks("polymarket", poly_lookup_ids))
        if kalshi_lookup_ids:
            tops.extend(await self.polyrouter.fetch_orderbooks("kalshi", kalshi_lookup_ids))

        for top in tops:
            with session_scope() as session:
                OrderBookService.upsert_top(
                    session,
                    venue=top["venue"],
                    venue_market_id=top["venue_market_id"],
                    outcome=top["outcome"],
                    best_bid=top["best_bid"],
                    best_ask=top["best_ask"],
                    bid_size=top["bid_size"],
                    ask_size=top["ask_size"],
                )

        self._mark_health(
            "polyrouter",
            ok=bool(tops),
            detail={
                "source": "polyrouter",
                "requested": len(poly_lookup_ids) + len(kalshi_lookup_ids),
                "updated": len(tops),
            },
        )

    def _active_market_data_source(self) -> str:
        configured = str(self.settings.market_data_source).strip().lower()
        if configured == "polyrouter" and self.settings.polyrouter_enable and self.settings.polyrouter_api_key:
            return "polyrouter"
        return "direct"

    def _upsert_event(self, session: Any, pair: Any) -> None:
        now = datetime.now(timezone.utc)
        stmt = insert(CanonicalEvent).values(
            id=pair.event_id,
            sport=pair.sport,
            competition=pair.competition,
            start_time_utc=pair.start_time_utc,
            home_team=pair.home_team,
            away_team=pair.away_team,
            title_canonical=pair.title_canonical,
            created_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "sport": pair.sport,
                "competition": pair.competition,
                "start_time_utc": pair.start_time_utc,
                "home_team": pair.home_team,
                "away_team": pair.away_team,
                "title_canonical": pair.title_canonical,
            },
        )
        session.execute(stmt)

    def _upsert_binding(self, session: Any, pair: Any, *, venue: str) -> None:
        market = pair.poly if venue == "POLY" else pair.kalshi
        now = datetime.now(timezone.utc)
        stmt = insert(MarketBinding).values(
            canonical_event_id=pair.event_id,
            venue=venue,
            venue_market_id=market.venue_market_id,
            outcome_schema="YES_NO",
            market_type=market.market_type,
            status=pair.status,
            confidence=pair.confidence,
            evidence_json=pair.evidence_json,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["venue", "venue_market_id"],
            set_={
                "canonical_event_id": pair.event_id,
                "outcome_schema": "YES_NO",
                "market_type": market.market_type,
                "status": pair.status,
                "confidence": pair.confidence,
                "evidence_json": pair.evidence_json,
                "updated_at": now,
            },
        )
        session.execute(stmt)

    def _seed_orderbook_from_market(self, session: Any, market: VenueMarket) -> None:
        yes_bid = _coerce_price(
            market.raw.get("yes_bid")
            or market.raw.get("bestBid")
            or market.raw.get("best_bid")
            or market.raw.get("bid")
        )
        yes_ask = _coerce_price(
            market.raw.get("yes_ask")
            or market.raw.get("bestAsk")
            or market.raw.get("best_ask")
            or market.raw.get("ask")
        )
        if yes_bid is None or yes_ask is None:
            return

        yes_bid_size = float(
            market.raw.get("yes_bid_size")
            or market.raw.get("bid_size")
            or market.raw.get("bestBidSize")
            or market.raw.get("size")
            or 0.0
        )
        yes_ask_size = float(
            market.raw.get("yes_ask_size")
            or market.raw.get("ask_size")
            or market.raw.get("bestAskSize")
            or market.raw.get("size")
            or 0.0
        )

        OrderBookService.upsert_top(
            session,
            venue=market.venue,
            venue_market_id=market.venue_market_id,
            outcome="YES",
            best_bid=yes_bid,
            best_ask=yes_ask,
            bid_size=yes_bid_size,
            ask_size=yes_ask_size,
        )

        no_bid = _coerce_price(market.raw.get("no_bid"))
        no_ask = _coerce_price(market.raw.get("no_ask"))
        if no_bid is not None and no_ask is not None:
            OrderBookService.upsert_top(
                session,
                venue=market.venue,
                venue_market_id=market.venue_market_id,
                outcome="NO",
                best_bid=no_bid,
                best_ask=no_ask,
                bid_size=yes_ask_size,
                ask_size=yes_bid_size,
            )

    def _apply_sport_toggles(self, markets: list[VenueMarket]) -> list[VenueMarket]:
        allowed: list[VenueMarket] = []
        for market in markets:
            if market.sport == "NBA" and not self.settings.enable_nba:
                continue
            if market.sport == "SOCCER" and not self.settings.enable_soccer:
                continue
            allowed.append(market)
        return allowed

    def _demo_markets(self) -> tuple[list[VenueMarket], list[VenueMarket]]:
        now = datetime.now(timezone.utc)
        nba_start = now + timedelta(hours=4)
        ucl_start = now + timedelta(hours=8)

        poly = [
            build_venue_market(
                venue="POLY",
                venue_market_id="poly-demo-nba-celtics-knicks",
                title="Boston Celtics vs New York Knicks",
                outcomes=["YES", "NO"],
                start_time=nba_start,
                sport_hint="NBA",
                competition_hint="NBA",
                raw={"bestBid": 0.52, "bestAsk": 0.54, "bestBidSize": 1200, "bestAskSize": 900},
            ),
            build_venue_market(
                venue="POLY",
                venue_market_id="poly-demo-ucl-gal-juv",
                title="Galatasaray vs Juventus",
                outcomes=["YES", "NO"],
                start_time=ucl_start,
                sport_hint="SOCCER",
                competition_hint="UCL",
                raw={"bestBid": 0.44, "bestAsk": 0.46, "bestBidSize": 860, "bestAskSize": 760},
            ),
        ]

        kalshi = [
            build_venue_market(
                venue="KALSHI",
                venue_market_id="kalshi-demo-nba-celtics-knicks",
                title="Boston Celtics vs New York Knicks",
                outcomes=["YES", "NO"],
                start_time=nba_start,
                sport_hint="NBA",
                competition_hint="NBA",
                raw={"yes_bid": 57, "yes_ask": 59, "yes_bid_size": 1400, "yes_ask_size": 1100},
            ),
            build_venue_market(
                venue="KALSHI",
                venue_market_id="kalshi-demo-ucl-gal-juv",
                title="Galatasaray vs Juventus",
                outcomes=["YES", "NO"],
                start_time=ucl_start,
                sport_hint="SOCCER",
                competition_hint="UCL",
                raw={"yes_bid": 49, "yes_ask": 51, "yes_bid_size": 900, "yes_ask_size": 1000},
            ),
        ]
        return poly, kalshi

    def _mark_health(self, name: str, *, ok: bool, detail: dict[str, Any] | None = None, error: str | None = None) -> None:
        row = self.health[name]
        row.ok = ok
        row.detail = detail or {}
        if ok:
            row.last_ok = datetime.now(timezone.utc).isoformat()
            row.last_error = None
        elif error:
            row.last_error = error


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
