export type Venue = "POLY" | "KALSHI";

export interface SignalRow {
  id: string;
  canonical_event_id: string;
  sport: "NBA" | "SOCCER" | string;
  competition: string | null;
  match: string;
  start_time_utc: string;
  outcome: "YES" | "NO" | string;
  buy_venue: Venue;
  sell_venue: Venue;
  buy_market_id: string;
  sell_market_id: string;
  buy_price: number;
  sell_price: number;
  size_suggested: number;
  edge_raw: number;
  edge_after_costs: number;
  confidence: number;
  status: string;
  created_at: string;
}

export interface OrderbookRow {
  venue: Venue;
  venue_market_id: string;
  outcome: string;
  best_bid: number;
  best_ask: number;
  bid_size: number;
  ask_size: number;
  ts: string;
}

export interface BindingRow {
  id: string;
  canonical_event_id: string;
  venue: Venue;
  venue_market_id: string;
  market_type: string;
  status: string;
  confidence: number;
  evidence_json: string;
  updated_at: string;
}

export interface PaperPosition {
  id: string;
  canonical_event_id: string;
  signal_id: string;
  outcome: string;
  buy_venue: Venue;
  sell_venue: Venue;
  buy_market_id: string;
  sell_market_id: string;
  size: number;
  entry_buy_price: number;
  entry_sell_price: number;
  fill_ratio: number;
  status: "OPEN" | "CLOSED";
  opened_at: string;
  closed_at: string | null;
  realized_pnl: number;
  unrealized_pnl: number;
}

export interface PortfolioStats {
  as_of: string;
  open_positions: number;
  closed_positions: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number;
  win_rate: number;
  avg_fill_ratio: number;
  avg_edge_captured: number;
  avg_slippage: number;
  equity_curve: Array<{ ts: string; equity: number; realized: number; unrealized: number }>;
}

export interface SnapshotPayload {
  type: "snapshot";
  ts: string;
  data_source?: "direct" | "polyrouter" | string;
  signals: SignalRow[];
  orderbooks: OrderbookRow[];
  equity_curve: Array<{ ts: string; equity: number; realized: number; unrealized: number }>;
}
