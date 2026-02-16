"use client";

import { useMemo, useState } from "react";

import { SignalRow } from "@/types/domain";

interface Props {
  rows: SignalRow[];
  onSelect: (row: SignalRow) => void;
}

type SortKey =
  | "edge_after_costs"
  | "confidence"
  | "start_time_utc"
  | "sport"
  | "competition"
  | "size_suggested";

export function SignalTable({ rows, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("edge_after_costs");
  const [desc, setDesc] = useState(true);

  const sorted = useMemo(() => {
    const cloned = [...rows];
    cloned.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") {
        return desc ? bv - av : av - bv;
      }
      return desc
        ? String(bv ?? "").localeCompare(String(av ?? ""))
        : String(av ?? "").localeCompare(String(bv ?? ""));
    });
    return cloned;
  }, [rows, sortKey, desc]);

  const triggerSort = (key: SortKey) => {
    if (sortKey === key) {
      setDesc((v) => !v);
      return;
    }
    setSortKey(key);
    setDesc(true);
  };

  return (
    <div className="card overflow-hidden rounded-xl">
      <div className="overflow-auto">
        <table className="w-full min-w-[1200px] text-sm">
          <thead className="table-head border-b border-white/10">
            <tr>
              <th className="px-3 py-3 text-left">
                <button onClick={() => triggerSort("sport")}>Sport/Comp</button>
              </th>
              <th className="px-3 py-3 text-left">Match</th>
              <th className="px-3 py-3 text-left">
                <button onClick={() => triggerSort("start_time_utc")}>Start Time</button>
              </th>
              <th className="px-3 py-3 text-left">Outcome</th>
              <th className="px-3 py-3 text-left">Buy@</th>
              <th className="px-3 py-3 text-left">Sell@</th>
              <th className="px-3 py-3 text-left">Edge%</th>
              <th className="px-3 py-3 text-left">
                <button onClick={() => triggerSort("edge_after_costs")}>EdgeAfterCosts%</button>
              </th>
              <th className="px-3 py-3 text-left">Depth(Size)</th>
              <th className="px-3 py-3 text-left">
                <button onClick={() => triggerSort("confidence")}>Confidence</button>
              </th>
              <th className="px-3 py-3 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.id}
                className="cursor-pointer border-b border-white/5 transition hover:bg-white/5"
                onClick={() => onSelect(row)}
              >
                <td className="px-3 py-2">
                  <div className="font-semibold">{row.sport}</div>
                  <div className="text-xs text-sky-100/60">{row.competition ?? "-"}</div>
                </td>
                <td className="px-3 py-2">{row.match}</td>
                <td className="px-3 py-2 text-xs">{new Date(row.start_time_utc).toLocaleString()}</td>
                <td className="px-3 py-2">{row.outcome}</td>
                <td className="px-3 py-2">
                  {row.buy_venue} @{row.buy_price.toFixed(3)}
                </td>
                <td className="px-3 py-2">
                  {row.sell_venue} @{row.sell_price.toFixed(3)}
                </td>
                <td className="px-3 py-2">{(row.edge_raw * 100).toFixed(2)}%</td>
                <td className="px-3 py-2 font-semibold text-emerald-300">
                  {(row.edge_after_costs * 100).toFixed(2)}%
                </td>
                <td className="px-3 py-2">{row.size_suggested.toFixed(2)}</td>
                <td className="px-3 py-2">{(row.confidence * 100).toFixed(1)}%</td>
                <td className="px-3 py-2">{row.status}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={11} className="px-3 py-8 text-center text-sky-100/60">
                  No opportunities match current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
