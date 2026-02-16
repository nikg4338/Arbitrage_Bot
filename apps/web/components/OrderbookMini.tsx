"use client";

import { OrderbookRow, SignalRow } from "@/types/domain";

interface Props {
  signal: SignalRow;
  orderbooks: OrderbookRow[];
}

export function OrderbookMini({ signal, orderbooks }: Props) {
  const buy = orderbooks.find(
    (row) => row.venue === signal.buy_venue && row.venue_market_id === signal.buy_market_id && row.outcome === signal.outcome
  );
  const sell = orderbooks.find(
    (row) => row.venue === signal.sell_venue && row.venue_market_id === signal.sell_market_id && row.outcome === signal.outcome
  );

  if (!buy || !sell) {
    return <p className="text-xs text-sky-100/60">No orderbook snapshot available for this signal yet.</p>;
  }

  const maxDepth = Math.max(buy.bid_size, buy.ask_size, sell.bid_size, sell.ask_size, 1);
  const width = (v: number) => `${Math.round((v / maxDepth) * 100)}%`;

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-white/10 p-3">
        <div className="mb-1 text-xs uppercase tracking-wide text-sky-100/70">
          Buy Venue ({signal.buy_venue}) {signal.buy_market_id}
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="mb-1 text-xs text-sky-100/60">Bid {buy.best_bid.toFixed(3)}</div>
            <div className="h-2 rounded bg-cyan-800/40">
              <div className="h-2 rounded bg-cyan-400" style={{ width: width(buy.bid_size) }} />
            </div>
            <div className="mt-1 text-xs">{buy.bid_size.toFixed(2)}</div>
          </div>
          <div>
            <div className="mb-1 text-xs text-sky-100/60">Ask {buy.best_ask.toFixed(3)}</div>
            <div className="h-2 rounded bg-amber-800/40">
              <div className="h-2 rounded bg-amber-400" style={{ width: width(buy.ask_size) }} />
            </div>
            <div className="mt-1 text-xs">{buy.ask_size.toFixed(2)}</div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-white/10 p-3">
        <div className="mb-1 text-xs uppercase tracking-wide text-sky-100/70">
          Sell Venue ({signal.sell_venue}) {signal.sell_market_id}
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="mb-1 text-xs text-sky-100/60">Bid {sell.best_bid.toFixed(3)}</div>
            <div className="h-2 rounded bg-cyan-800/40">
              <div className="h-2 rounded bg-cyan-400" style={{ width: width(sell.bid_size) }} />
            </div>
            <div className="mt-1 text-xs">{sell.bid_size.toFixed(2)}</div>
          </div>
          <div>
            <div className="mb-1 text-xs text-sky-100/60">Ask {sell.best_ask.toFixed(3)}</div>
            <div className="h-2 rounded bg-amber-800/40">
              <div className="h-2 rounded bg-amber-400" style={{ width: width(sell.ask_size) }} />
            </div>
            <div className="mt-1 text-xs">{sell.ask_size.toFixed(2)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
