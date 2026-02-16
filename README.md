# Cross-Exchange Mispricing Detector (Polymarket vs Kalshi)

Read-only decision-support + paper simulation system for **NBA** and **Soccer (EPL/UCL/UEL/LALIGA)** winner markets.

- No real order placement
- No geofence/VPN bypass logic
- Persistent mappings, prices, and signals for auditability

## Stack

- Backend: Python 3.11, FastAPI, asyncio, SQLModel/SQLAlchemy, SQLite
- Frontend: Next.js (TypeScript), Tailwind, Recharts
- Realtime: WebSocket stream from backend to UI (`/signals/ws`)

## Repo layout

```text
/apps
  /api
  /web
/packages
  /core
/tests
README.md
.env.example
```

## Features implemented

- Multi-connector ingestion
  - Polymarket Gamma market discovery
  - Polymarket CLOB top-of-book snapshot polling (read-only)
  - Kalshi REST discovery
  - Kalshi websocket connector with backoff/reconnect (read-only)
- Robust normalization + matching resolver
  - Team aliases and stopword cleanup
  - Sport/competition/time blocking
  - Weighted score (team/time/title)
  - Decisions: `AUTO`, `REVIEW`, `OVERRIDE`, `REJECTED`
  - 3-way soccer markets ingested and held in review flow
- Persistent domain model in SQLite
  - `CanonicalEvent`, `MarketBinding`, `OrderBookTop`, `MispricingSignal`, paper-trading tables
- Mispricing engine
  - Computes edges for YES/NO outcomes
  - Applies venue fees + slippage buffers
  - Depth checks + event time guardrails
- Suggested manual trade recipe cards
- Paper trading simulator
  - Two-leg pair position creation from signal
  - Fill model (crossing, at-best, inside spread)
  - MTM updates, manual close, auto-close at event start
  - Portfolio stats and equity curve
- Operational reliability
  - Structured JSON logs
  - `/health` connector status
  - Deterministic event IDs and DB upserts to avoid duplicates

## Quickstart

### 1) Backend

```bash
cp .env apps/api/.env
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2) Frontend

```bash
cd apps/web
npm install
cat > .env.local <<EOF2
NEXT_PUBLIC_API_HTTP_URL=http://localhost:8000
NEXT_PUBLIC_API_WS_URL=ws://localhost:8000/signals/ws
EOF2
npm run dev
```

### 3) Open dashboard

- Open `http://localhost:3000`
- Dashboard shows top opportunities and live updates
- Mappings page: `http://localhost:3000/mappings`
- Paper portfolio: `http://localhost:3000/paper`

## Typical workflow

1. Review mappings in **Mappings** page.
2. Approve (`OVERRIDE`) or reject uncertain pairs.
3. Watch **Top Opportunities** update in realtime.
4. Open a signal drawer and inspect mapping evidence/orderbook.
5. Click **Simulate** to create a paper position.
6. Monitor paper PnL and execution quality in **Paper Portfolio**.

## Optional Polyrouter Mode

The backend defaults to direct venue connectors (`Polymarket Gamma/CLOB + Kalshi REST`).
To route market discovery + orderbooks through Polyrouter instead, set in `apps/api/.env`:

```bash
MARKET_DATA_SOURCE=polyrouter
POLYROUTER_ENABLE=true
POLYROUTER_KEY=your_key_here
```

Optional tuning:

```bash
POLYROUTER_BASE_URL=https://api-v2.polyrouter.io
POLYROUTER_REQ_PER_MIN=80
POLYROUTER_MARKET_PAGE_LIMIT=4
POLYROUTER_ORDERBOOK_BATCH_SIZE=50
```

## Demo Fallback Toggle

By default, demo market seeding is disabled so only live data is shown.
If you want offline/demo behavior explicitly, set:

```bash
ENABLE_DEMO_FALLBACK=true
```

## API endpoints

- `GET /health`
- `GET /markets/events`
- `GET /markets/{event_id}/bindings`
- `GET /markets/orderbooks`
- `GET /mappings`
- `GET /mappings/review`
- `POST /mappings/{binding_id}/approve`
- `POST /mappings/{binding_id}/reject`
- `POST /mappings/override`
- `GET /signals`
- `GET /signals/snapshot`
- `WS /signals/ws`
- `POST /paper/simulate`
- `GET /paper/positions`
- `POST /paper/positions/{position_id}/close`
- `GET /paper/stats`

## Tests

```bash
cd apps/api
source .venv/bin/activate
pytest ../../tests -q
```

Included tests:
- `tests/test_resolver.py`
- `tests/test_pricing.py`
- `tests/test_signals.py`

## Screenshot instructions

1. Start backend + frontend.
2. Open the dashboard pages in browser.
3. Capture:
   - Dashboard opportunities table + detail drawer
   - Mappings review/approve controls
   - Paper portfolio with equity chart
4. Save images under `docs/screenshots/` (optional) and reference them in PR notes.

## Notes

- Connectors are strictly read-only. No live trading or order placement endpoints exist.
- If external market APIs are unavailable, the scheduler seeds demo markets so UI and simulator remain usable locally.
# Arbitrage_Bot
