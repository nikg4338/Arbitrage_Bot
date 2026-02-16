"use client";

import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { BindingRow, OrderbookRow, SignalRow } from "@/types/domain";
import { OrderbookMini } from "@/components/OrderbookMini";

interface Props {
  signal: SignalRow | null;
  bindings: BindingRow[];
  orderbooks: OrderbookRow[];
  onClose: () => void;
}

export function OpportunityDrawer({ signal, bindings, orderbooks, onClose }: Props) {
  const [simulating, setSimulating] = useState(false);
  const [simulateMessage, setSimulateMessage] = useState<string | null>(null);

  const tradeRecipe = useMemo(() => {
    if (!signal) {
      return null;
    }
    const worstCaseEdge = Math.max(0, signal.edge_after_costs - 0.01);
    return {
      buy: `Buy ${signal.outcome} on ${signal.buy_venue} @ <= ${signal.buy_price.toFixed(3)}`,
      sell: `Sell ${signal.outcome} on ${signal.sell_venue} @ >= ${signal.sell_price.toFixed(3)}`,
      size: signal.size_suggested.toFixed(2),
      expectedEdge: `${(signal.edge_after_costs * 100).toFixed(2)}%`,
      worstCaseEdge: `${(worstCaseEdge * 100).toFixed(2)}%`
    };
  }, [signal]);

  if (!signal) {
    return (
      <aside className="card min-h-[500px] rounded-xl p-4">
        <p className="text-sm text-sky-100/70">Select an opportunity to inspect mapping evidence and simulation controls.</p>
      </aside>
    );
  }

  const simulate = async () => {
    setSimulating(true);
    setSimulateMessage(null);
    try {
      const result = await api.simulate({ signal_id: signal.id });
      setSimulateMessage(`Simulation opened: ${result.id} (fill ratio ${(result.fill_ratio * 100).toFixed(1)}%)`);
    } catch (err) {
      setSimulateMessage(err instanceof Error ? err.message : "simulate failed");
    } finally {
      setSimulating(false);
    }
  };

  const copy = async (value: string) => {
    await navigator.clipboard.writeText(value);
  };

  return (
    <aside className="card min-h-[500px] rounded-xl p-4">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-lg">Opportunity Detail</h3>
          <p className="text-xs text-sky-100/70">{signal.match}</p>
        </div>
        <button className="rounded border border-white/20 px-2 py-1 text-xs" onClick={onClose}>
          Clear
        </button>
      </div>

      <section className="space-y-2 rounded-lg border border-white/10 p-3">
        <div className="text-xs uppercase tracking-wide text-sky-100/70">Trade Recipe</div>
        <div className="text-sm">{tradeRecipe?.buy}</div>
        <div className="text-sm">{tradeRecipe?.sell}</div>
        <div className="text-sm">Suggested size: {tradeRecipe?.size}</div>
        <div className="text-sm text-emerald-300">Expected edge: {tradeRecipe?.expectedEdge}</div>
        <div className="text-sm text-amber-200">Worst-case edge: {tradeRecipe?.worstCaseEdge}</div>
        <div className="mt-2 flex gap-2">
          <button
            className="rounded bg-emerald-500 px-3 py-1 text-xs font-semibold text-slate-900 disabled:opacity-60"
            onClick={simulate}
            disabled={simulating}
          >
            {simulating ? "Simulating..." : "Simulate"}
          </button>
          <button
            className="rounded border border-white/20 px-3 py-1 text-xs"
            onClick={() =>
              copy(
                JSON.stringify(
                  {
                    buy_market: signal.buy_market_id,
                    sell_market: signal.sell_market_id,
                    buy_limit: signal.buy_price,
                    sell_limit: signal.sell_price,
                    size: signal.size_suggested
                  },
                  null,
                  2
                )
              )
            }
          >
            Copy IDs + Limits
          </button>
        </div>
        {simulateMessage && <div className="text-xs text-sky-100/80">{simulateMessage}</div>}
      </section>

      <section className="mt-4 space-y-2 rounded-lg border border-white/10 p-3">
        <div className="text-xs uppercase tracking-wide text-sky-100/70">Mapping Evidence</div>
        {bindings.length === 0 && <p className="text-xs text-sky-100/60">No binding records found for this event.</p>}
        {bindings.map((binding) => (
          <div key={binding.id} className="rounded border border-white/10 p-2 text-xs">
            <div>
              {binding.venue} / {binding.venue_market_id}
            </div>
            <div>
              Status: {binding.status} | Confidence {(binding.confidence * 100).toFixed(1)}%
            </div>
            <div className="mt-1 whitespace-pre-wrap text-sky-100/70">{binding.evidence_json}</div>
          </div>
        ))}
      </section>

      <section className="mt-4 rounded-lg border border-white/10 p-3">
        <div className="mb-2 text-xs uppercase tracking-wide text-sky-100/70">Orderbook Mini View</div>
        <OrderbookMini signal={signal} orderbooks={orderbooks} />
      </section>
    </aside>
  );
}
