import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  SessionsMap,
  SessionMessage,
  WsSessionsMessage,
  WsMessagesMessage,
} from '@/types';
import { api } from '@/api';

/** Normalise status values — upstream may return {type:"busy"} or "busy". */
function normaliseSessions(raw: Record<string, unknown>): SessionsMap {
  const out: SessionsMap = {};
  for (const [sid, val] of Object.entries(raw)) {
    out[sid] = typeof val === 'string' ? val : (val as any)?.type ?? 'unknown';
  }
  return out;
}

/**
 * Live OpenCode session stream for a host.
 *
 * 1. Initial REST load on mount.
 * 2. WebSocket receives **full** message lists from the backend —
 *    the frontend simply replaces state; no delta / append logic.
 * 3. Periodic REST poll every 5 s as safety-net.
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

  // ── REST load + periodic refresh ───────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const sessData: any = await api.openCodeSessions(host);
        if (cancelled) return;
        const normalised = normaliseSessions(sessData);
        setSessions(normalised);

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
        // host unreachable
      }
    };

    load();
    const interval = setInterval(load, 5_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [host]);

  // ── WebSocket live stream ──────────────────────────────────────
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
          setSessions(normaliseSessions((msg as WsSessionsMessage).data));
        } else if (msg.type === 'messages') {
          const m = msg as WsMessagesMessage & { full?: boolean };
          // Backend sends full message list — always replace.
          setMessagesBySession((prev) => ({
            ...prev,
            [m.session_id]: Array.isArray(m.data) ? m.data : [],
          }));
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
