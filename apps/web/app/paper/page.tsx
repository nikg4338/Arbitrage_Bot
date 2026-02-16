"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { api } from "@/lib/api";
import { PaperPosition, PortfolioStats } from "@/types/domain";

export default function PaperPage() {
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    try {
      const [pos, stat] = await Promise.all([api.positions(), api.paperStats()]);
      setPositions(pos as PaperPosition[]);
      setStats(stat as PortfolioStats);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "failed to load paper portfolio");
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, []);

  const closePosition = async (id: string) => {
    try {
      await api.closePosition(id);
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "close failed");
    }
  };

  const openPositions = useMemo(
    () => positions.filter((row) => row.status === "OPEN"),
    [positions]
  );
  const closedPositions = useMemo(
    () => positions.filter((row) => row.status === "CLOSED"),
    [positions]
  );

  return (
    <div className="space-y-4">
      <section className="grid gap-3 md:grid-cols-5">
        <MetricCard label="Equity" value={stats ? stats.equity.toFixed(2) : "-"} />
        <MetricCard label="Realized PnL" value={stats ? stats.realized_pnl.toFixed(2) : "-"} />
        <MetricCard label="Unrealized PnL" value={stats ? stats.unrealized_pnl.toFixed(2) : "-"} />
        <MetricCard label="Win Rate" value={stats ? `${(stats.win_rate * 100).toFixed(1)}%` : "-"} />
        <MetricCard label="Avg Fill Ratio" value={stats ? `${(stats.avg_fill_ratio * 100).toFixed(1)}%` : "-"} />
      </section>

      <section className="card rounded-xl p-4">
        <h2 className="mb-3 font-display text-xl">Equity Curve</h2>
        <div className="h-[280px] w-full">
          <ResponsiveContainer>
            <LineChart data={stats?.equity_curve ?? []} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="ts"
                tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                stroke="rgba(255,255,255,0.5)"
                fontSize={12}
              />
              <YAxis stroke="rgba(255,255,255,0.5)" fontSize={12} />
              <Tooltip
                labelFormatter={(label) => new Date(label).toLocaleString()}
                contentStyle={{ background: "#0d2033", border: "1px solid rgba(255,255,255,0.2)" }}
              />
              <Line type="monotone" dataKey="equity" stroke="#20c997" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card rounded-xl p-4">
          <h3 className="mb-3 font-semibold">Open Positions</h3>
          <PositionTable rows={openPositions} onClose={closePosition} />
        </div>
        <div className="card rounded-xl p-4">
          <h3 className="mb-3 font-semibold">Closed Positions</h3>
          <PositionTable rows={closedPositions} readOnly />
        </div>
      </section>

      {message && <p className="text-sm text-amber-200">{message}</p>}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="card rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-sky-100/70">{label}</div>
      <div className="mt-1 font-display text-2xl">{value}</div>
    </div>
  );
}

function PositionTable({
  rows,
  onClose,
  readOnly
}: {
  rows: PaperPosition[];
  onClose?: (id: string) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="table-head border-b border-white/10">
          <tr>
            <th className="px-2 py-2 text-left">Signal</th>
            <th className="px-2 py-2 text-left">Size</th>
            <th className="px-2 py-2 text-left">Entry Spread</th>
            <th className="px-2 py-2 text-left">Fill</th>
            <th className="px-2 py-2 text-left">PnL</th>
            <th className="px-2 py-2 text-left">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-white/5">
              <td className="px-2 py-2 text-xs">{row.signal_id.slice(0, 8)}</td>
              <td className="px-2 py-2">{row.size.toFixed(2)}</td>
              <td className="px-2 py-2">{(row.entry_sell_price - row.entry_buy_price).toFixed(4)}</td>
              <td className="px-2 py-2">{(row.fill_ratio * 100).toFixed(1)}%</td>
              <td className="px-2 py-2">
                {(row.realized_pnl + row.unrealized_pnl).toFixed(3)}
              </td>
              <td className="px-2 py-2">
                {readOnly ? (
                  <span className="text-xs text-sky-100/60">Closed</span>
                ) : (
                  <button
                    className="rounded bg-amber-400 px-2 py-1 text-xs text-black"
                    onClick={() => onClose?.(row.id)}
                  >
                    Close
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-2 py-6 text-center text-sky-100/70">
                No positions.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
