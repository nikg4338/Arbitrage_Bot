import { API_HTTP_BASE } from "@/lib/config";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_HTTP_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status} ${text}`);
  }
  return (await response.json()) as T;
}

export const api = {
  snapshot: () => request("/signals/snapshot"),
  reviewMappings: () => request("/mappings/review"),
  allMappings: () => request("/mappings"),
  approveMapping: (id: string) => request(`/mappings/${id}/approve`, { method: "POST" }),
  rejectMapping: (id: string) => request(`/mappings/${id}/reject`, { method: "POST" }),
  overridePair: (payload: {
    poly_market_id: string;
    kalshi_market_id: string;
    canonical_event_id?: string;
  }) => request("/mappings/override", { method: "POST", body: JSON.stringify(payload) }),
  eventBindings: (eventId: string) => request(`/markets/${eventId}/bindings`),
  simulate: (payload: { signal_id: string; size?: number }) =>
    request("/paper/simulate", { method: "POST", body: JSON.stringify(payload) }),
  positions: () => request("/paper/positions"),
  closePosition: (positionId: string) => request(`/paper/positions/${positionId}/close`, { method: "POST" }),
  paperStats: () => request("/paper/stats")
};
