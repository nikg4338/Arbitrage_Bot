"use client";

import { useEffect, useRef, useState } from "react";

import { API_WS_URL } from "@/lib/config";
import { SnapshotPayload } from "@/types/domain";

export function useSignalStream(initial: SnapshotPayload | null = null) {
  const [snapshot, setSnapshot] = useState<SnapshotPayload | null>(initial);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let websocket: WebSocket | null = null;
    let timeout: number | undefined;
    let cancelled = false;

    const connect = () => {
      websocket = new WebSocket(API_WS_URL);

      websocket.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
        setError(null);
      };

      websocket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as SnapshotPayload;
          if (parsed.type === "snapshot") {
            setSnapshot(parsed);
          }
        } catch {
          // Ignore malformed payloads.
        }
      };

      websocket.onclose = () => {
        setConnected(false);
        if (cancelled) {
          return;
        }
        retryRef.current += 1;
        const delay = Math.min(10000, 500 * Math.pow(1.7, retryRef.current));
        timeout = window.setTimeout(connect, delay);
      };

      websocket.onerror = () => {
        setError("WebSocket disconnected. Retrying...");
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (timeout) {
        window.clearTimeout(timeout);
      }
      websocket?.close();
    };
  }, []);

  return { snapshot, connected, error };
}
