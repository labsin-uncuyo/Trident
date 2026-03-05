import { useState, useEffect, useRef, useCallback } from 'react';
import type { TimelineEntry, WsTimelineMessage } from '@/types';
import { api } from '@/api';

/**
 * Live timeline stream for an agent.
 * Loads existing entries via REST, then tails new ones via WebSocket.
 * Also re-polls REST every 10s as a fallback in case the WS tail
 * misses entries (e.g. file didn't exist when WS first connected).
 */
export function useTimelineStream(agent: string) {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);

  // ── REST load + periodic refresh ─────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = () => {
      api
        .timeline(agent)
        .then((r: any) => {
          if (cancelled) return;
          const fetched: TimelineEntry[] = r?.entries ?? [];
          if (fetched.length > 0) {
            setEntries((prev) => (fetched.length > prev.length ? fetched : prev));
          }
        })
        .catch(() => {});
    };

    load();
    const interval = setInterval(load, 10_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [agent]);

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/timeline/${agent}/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      backoffRef.current = 1000;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsTimelineMessage;
        if (msg.type === 'timeline' && msg.data) {
          setEntries((prev) => [...prev, msg.data]);
        }
      } catch {}
    };

    ws.onclose = () => {
      setConnected(false);
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, 30000);
      reconnectTimer.current = setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
  }, [agent]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { entries, connected };
}
