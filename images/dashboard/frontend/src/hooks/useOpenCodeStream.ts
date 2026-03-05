import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  SessionsMap,
  SessionMessage,
  WsSessionsMessage,
  WsMessagesMessage,
} from '@/types';
import { api } from '@/api';

/**
 * Live OpenCode session stream for a host.
 * Loads initial state via REST, then tails via WebSocket.
 */
export function useOpenCodeStream(host: string) {
  const [sessions, setSessions] = useState<SessionsMap>({});
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, SessionMessage[]>
  >({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);

  // ── Initial REST load ──────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const sessData: any = await api.openCodeSessions(host);
        if (cancelled) return;

        // sessData is { sid: status } — normalise in case of objects
        const normalised: SessionsMap = {};
        for (const [sid, val] of Object.entries(sessData)) {
          normalised[sid] =
            typeof val === 'string' ? val : (val as any)?.type ?? 'unknown';
        }
        setSessions(normalised);

        // Fetch messages for every session
        const bySession: Record<string, SessionMessage[]> = {};
        for (const sid of Object.keys(normalised)) {
          try {
            const msgs: any = await api.openCodeMessages(host, sid);
            if (cancelled) return;
            bySession[sid] = Array.isArray(msgs) ? msgs : [];
          } catch {
            bySession[sid] = [];
          }
        }
        setMessagesBySession(bySession);
      } catch {
        // host unreachable — will be populated by WS later
      }
    })();

    return () => { cancelled = true; };
  }, [host]);

  // ── WebSocket live tail ────────────────────────────────────────
  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/opencode/${host}/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      backoffRef.current = 1000;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'sessions') {
          const sessMsg = msg as WsSessionsMessage;
          // Normalise values in case the backend leaks objects
          const normalised: SessionsMap = {};
          for (const [sid, val] of Object.entries(sessMsg.data)) {
            normalised[sid] =
              typeof val === 'string' ? val : (val as any)?.type ?? 'unknown';
          }
          setSessions(normalised);
        } else if (msg.type === 'messages') {
          const msgsMsg = msg as WsMessagesMessage;
          setMessagesBySession((prev) => {
            const existing = prev[msgsMsg.session_id] || [];
            // The backend sends a "total" field — if the new data
            // together with existing equals total, just append the delta.
            // Otherwise replace to avoid duplicates on reconnect.
            const total = (msgsMsg as any).total ?? 0;
            if (total > 0 && existing.length + msgsMsg.data.length === total) {
              return { ...prev, [msgsMsg.session_id]: [...existing, ...msgsMsg.data] };
            }
            // Mismatch — the safest approach is: if total matches existing
            // length, nothing new. If total > existing, re-fetch would be
            // ideal, but we don't have async here. Just replace with all
            // available server-side messages represented by total.
            // Since the WS data is the delta, and we can't know where we
            // are, replace entirely when the existing count plus delta
            // doesn't match total.
            if (existing.length >= total && total > 0) {
              return prev; // already up to date
            }
            // For the initial WS push (existing empty), just set it
            if (existing.length === 0) {
              return { ...prev, [msgsMsg.session_id]: msgsMsg.data };
            }
            // Fallback: append (may sometimes duplicate, but better than
            // losing data)
            return { ...prev, [msgsMsg.session_id]: [...existing, ...msgsMsg.data] };
          });
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
  }, [host]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { sessions, messagesBySession, connected };
}
