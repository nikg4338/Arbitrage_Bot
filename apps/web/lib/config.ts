export const API_HTTP_BASE =
  process.env.NEXT_PUBLIC_API_HTTP_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
export const API_WS_URL = process.env.NEXT_PUBLIC_API_WS_URL ?? "ws://localhost:8000/signals/ws";
