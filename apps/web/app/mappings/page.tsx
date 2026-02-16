"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { BindingRow } from "@/types/domain";

export default function MappingsPage() {
  const [reviewRows, setReviewRows] = useState<BindingRow[]>([]);
  const [allRows, setAllRows] = useState<BindingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const [polyMarketId, setPolyMarketId] = useState("");
  const [kalshiMarketId, setKalshiMarketId] = useState("");
  const [canonicalEventId, setCanonicalEventId] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const [review, all] = await Promise.all([api.reviewMappings(), api.allMappings()]);
      setReviewRows(review as BindingRow[]);
      setAllRows(all as BindingRow[]);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "failed to load mappings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const approve = async (id: string) => {
    await api.approveMapping(id);
    setMessage(`Approved mapping ${id}`);
    await load();
  };

  const reject = async (id: string) => {
    await api.rejectMapping(id);
    setMessage(`Rejected mapping ${id}`);
    await load();
  };

  const overridePair = async () => {
    try {
      await api.overridePair({
        poly_market_id: polyMarketId,
        kalshi_market_id: kalshiMarketId,
        canonical_event_id: canonicalEventId || undefined
      });
      setMessage("Pair manually overridden to OVERRIDE status");
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "override failed");
    }
  };

  return (
    <div className="space-y-4">
      <section className="card rounded-xl p-4">
        <h2 className="font-display text-xl">Review Queue</h2>
        <p className="text-sm text-sky-100/70">Approve or reject resolver candidates before they become tradable signals.</p>
        {message && <p className="mt-2 text-xs text-amber-200">{message}</p>}
      </section>

      <section className="card rounded-xl p-4">
        <h3 className="font-semibold">Manual Override Editor</h3>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          <input
            className="rounded bg-black/20 p-2 text-sm"
            placeholder="Polymarket market id"
            value={polyMarketId}
            onChange={(e) => setPolyMarketId(e.target.value)}
          />
          <input
            className="rounded bg-black/20 p-2 text-sm"
            placeholder="Kalshi market id"
            value={kalshiMarketId}
            onChange={(e) => setKalshiMarketId(e.target.value)}
          />
          <input
            className="rounded bg-black/20 p-2 text-sm"
            placeholder="Canonical event id (optional)"
            value={canonicalEventId}
            onChange={(e) => setCanonicalEventId(e.target.value)}
          />
        </div>
        <button className="mt-3 rounded bg-cyan-500 px-3 py-2 text-sm text-black" onClick={overridePair}>
          Apply Override
        </button>
      </section>

      <section className="card overflow-auto rounded-xl p-0">
        <table className="w-full min-w-[1000px] text-sm">
          <thead className="table-head border-b border-white/10">
            <tr>
              <th className="px-3 py-3 text-left">ID</th>
              <th className="px-3 py-3 text-left">Event</th>
              <th className="px-3 py-3 text-left">Venue</th>
              <th className="px-3 py-3 text-left">Market</th>
              <th className="px-3 py-3 text-left">Status</th>
              <th className="px-3 py-3 text-left">Confidence</th>
              <th className="px-3 py-3 text-left">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(reviewRows.length ? reviewRows : allRows).map((row) => (
              <tr key={row.id} className="border-b border-white/5">
                <td className="px-3 py-2 text-xs">{row.id.slice(0, 8)}</td>
                <td className="px-3 py-2 text-xs">{row.canonical_event_id}</td>
                <td className="px-3 py-2">{row.venue}</td>
                <td className="px-3 py-2">{row.venue_market_id}</td>
                <td className="px-3 py-2">{row.status}</td>
                <td className="px-3 py-2">{(row.confidence * 100).toFixed(1)}%</td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <button className="rounded bg-emerald-500 px-2 py-1 text-xs text-black" onClick={() => approve(row.id)}>
                      Approve
                    </button>
                    <button className="rounded bg-rose-500 px-2 py-1 text-xs" onClick={() => reject(row.id)}>
                      Reject
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {loading && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sky-100/70">
                  Loading mappings...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
