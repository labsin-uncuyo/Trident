import { useState, useEffect, useRef, useCallback } from 'react';
import type { TimelineEntry, WsTimelineMessage } from '@/types';
import { api } from '@/api';

/**
 * Live timeline stream for an agent.
 *
 * 1. REST poll every 3 s — always authoritative (reads the file on disk).
 * 2. WebSocket pushes new entries as they appear for lower latency.
 *    The WS backend polls the same file every 2 s and sends any new lines.
 *
 * The REST poll acts as safety-net so the UI is never stale for more
 * than a few seconds, even if the WS connection drops.
 */
export function useTimelineStream(agent: string) {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);

  // ── REST poll every 3 s ──────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = () => {
      api
        .timeline(agent)
        .then((r: any) => {
          if (cancelled) return;
          const fetched: TimelineEntry[] = r?.entries ?? [];
          // Replace if the server has more entries than local state
          setEntries((prev) => (fetched.length > prev.length ? fetched : prev));
        })
        .catch(() => {});
    };

    load();
    const interval = setInterval(load, 3_000);

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
        const msg = JSON.parse(event.data);
        if (msg.type === 'timeline' && msg.full && Array.isArray(msg.data)) {
          // Full replacement — no duplicates
          setEntries(msg.data as TimelineEntry[]);
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
