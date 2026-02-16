"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { OpportunityDrawer } from "@/components/OpportunityDrawer";
import { SignalTable } from "@/components/SignalTable";
import { api } from "@/lib/api";
import { useSignalStream } from "@/lib/useSignalStream";
import { BindingRow, SignalRow } from "@/types/domain";

export default function DashboardPage() {
  const { snapshot, connected, error } = useSignalStream(null);
  const [selected, setSelected] = useState<SignalRow | null>(null);
  const [bindings, setBindings] = useState<BindingRow[]>([]);

  const [sport, setSport] = useState("ALL");
  const [competition, setCompetition] = useState("ALL");
  const [venue, setVenue] = useState("ALL");
  const [minEdge, setMinEdge] = useState(0.8);
  const [minConfidence, setMinConfidence] = useState(0.75);
  const [startWindowHours, setStartWindowHours] = useState(48);

  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [alertThreshold, setAlertThreshold] = useState(1.5);
  const seenSignalRef = useRef<string | null>(null);

  const signals = snapshot?.signals ?? [];
  const orderbooks = snapshot?.orderbooks ?? [];

  const filteredSignals = useMemo(() => {
    const now = Date.now();
    const windowMs = startWindowHours * 3600 * 1000;
    return signals.filter((signal) => {
      if (sport !== "ALL" && signal.sport !== sport) {
        return false;
      }
      if (competition !== "ALL" && signal.competition !== competition) {
        return false;
      }
      if (venue !== "ALL" && signal.buy_venue !== venue && signal.sell_venue !== venue) {
        return false;
      }
      if (signal.edge_after_costs * 100 < minEdge) {
        return false;
      }
      if (signal.confidence < minConfidence) {
        return false;
      }
      const start = new Date(signal.start_time_utc).getTime();
      if (Number.isFinite(start) && start - now > windowMs) {
        return false;
      }
      return true;
    });
  }, [signals, sport, competition, venue, minEdge, minConfidence, startWindowHours]);

  useEffect(() => {
    if (!selected) {
      setBindings([]);
      return;
    }

    api
      .eventBindings(selected.canonical_event_id)
      .then((rows) => setBindings(rows as BindingRow[]))
      .catch(() => setBindings([]));
  }, [selected]);

  useEffect(() => {
    if (!notificationsEnabled || typeof window === "undefined") {
      return;
    }

    const top = filteredSignals[0];
    if (!top) {
      return;
    }
    if (top.edge_after_costs * 100 < alertThreshold) {
      return;
    }
    if (seenSignalRef.current === top.id) {
      return;
    }
    seenSignalRef.current = top.id;

    if (Notification.permission === "granted") {
      new Notification(`Signal ${top.match}`, {
        body: `${top.outcome}: ${(top.edge_after_costs * 100).toFixed(2)}% after costs`
      });
    }
  }, [filteredSignals, notificationsEnabled, alertThreshold]);

  const enableNotifications = async () => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      return;
    }
    const permission = await Notification.requestPermission();
    setNotificationsEnabled(permission === "granted");
  };

  const summary = useMemo(() => {
    if (filteredSignals.length === 0) {
      return { avgEdge: 0, topEdge: 0 };
    }
    const avgEdge =
      filteredSignals.reduce((sum, row) => sum + row.edge_after_costs, 0) / filteredSignals.length;
    const topEdge = Math.max(...filteredSignals.map((row) => row.edge_after_costs));
    return { avgEdge: avgEdge * 100, topEdge: topEdge * 100 };
  }, [filteredSignals]);

  return (
    <div className="space-y-4">
      <section className="grid gap-3 md:grid-cols-4">
        <div className="card rounded-xl p-4">
          <div className="text-xs uppercase tracking-wide text-sky-100/70">Connection</div>
          <div className={`mt-1 font-semibold ${connected ? "text-emerald-300" : "text-amber-200"}`}>
            {connected ? "Realtime Connected" : "Disconnected"}
          </div>
          {error && <p className="mt-1 text-xs text-amber-200">{error}</p>}
        </div>
        <div className="card rounded-xl p-4">
          <div className="text-xs uppercase tracking-wide text-sky-100/70">Visible Opportunities</div>
          <div className="mt-1 font-display text-2xl">{filteredSignals.length}</div>
        </div>
        <div className="card rounded-xl p-4">
          <div className="text-xs uppercase tracking-wide text-sky-100/70">Top Edge After Costs</div>
          <div className="mt-1 font-display text-2xl text-emerald-300">{summary.topEdge.toFixed(2)}%</div>
        </div>
        <div className="card rounded-xl p-4">
          <div className="text-xs uppercase tracking-wide text-sky-100/70">Average Edge After Costs</div>
          <div className="mt-1 font-display text-2xl">{summary.avgEdge.toFixed(2)}%</div>
        </div>
      </section>

      <section className="card rounded-xl p-4">
        <div className="grid gap-3 md:grid-cols-7">
          <label className="text-xs">
            Sport
            <select className="mt-1 w-full rounded bg-black/20 p-2" value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="ALL">All</option>
              <option value="NBA">NBA</option>
              <option value="SOCCER">Soccer</option>
            </select>
          </label>

          <label className="text-xs">
            Competition
            <select
              className="mt-1 w-full rounded bg-black/20 p-2"
              value={competition}
              onChange={(e) => setCompetition(e.target.value)}
            >
              <option value="ALL">All</option>
              <option value="NBA">NBA</option>
              <option value="EPL">EPL</option>
              <option value="UCL">UCL</option>
              <option value="UEL">UEL</option>
              <option value="LALIGA">LALIGA</option>
            </select>
          </label>

          <label className="text-xs">
            Venue Availability
            <select className="mt-1 w-full rounded bg-black/20 p-2" value={venue} onChange={(e) => setVenue(e.target.value)}>
              <option value="ALL">All</option>
              <option value="POLY">Polymarket</option>
              <option value="KALSHI">Kalshi</option>
            </select>
          </label>

          <label className="text-xs">
            Min Edge %
            <input
              className="mt-1 w-full rounded bg-black/20 p-2"
              type="number"
              step="0.1"
              value={minEdge}
              onChange={(e) => setMinEdge(Number(e.target.value))}
            />
          </label>

          <label className="text-xs">
            Min Confidence
            <input
              className="mt-1 w-full rounded bg-black/20 p-2"
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
            />
          </label>

          <label className="text-xs">
            Start Window (hours)
            <input
              className="mt-1 w-full rounded bg-black/20 p-2"
              type="number"
              step="1"
              min={1}
              value={startWindowHours}
              onChange={(e) => setStartWindowHours(Number(e.target.value))}
            />
          </label>

          <div className="text-xs">
            Alerts
            <div className="mt-1 flex gap-2">
              <button className="rounded bg-cyan-500 px-3 py-2 text-black" onClick={enableNotifications}>
                Enable
              </button>
              <input
                className="w-full rounded bg-black/20 p-2"
                type="number"
                step="0.1"
                value={alertThreshold}
                onChange={(e) => setAlertThreshold(Number(e.target.value))}
                title="Threshold edge percentage for notifications"
              />
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <SignalTable rows={filteredSignals} onSelect={setSelected} />
        <OpportunityDrawer signal={selected} bindings={bindings} orderbooks={orderbooks} onClose={() => setSelected(null)} />
      </section>
    </div>
  );
}
