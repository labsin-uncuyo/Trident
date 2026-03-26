import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  SessionsMap,
  SessionMessage,
  OpenCodeStatePayload,
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
export function useOpenCodeStream(_host?: string) {
  const [sessions, setSessions] = useState<SessionsMap>({});
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, SessionMessage[]>
  >({});
  const [sessionSources, setSessionSources] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);

  // ── REST load + periodic refresh ───────────────────────────────
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const state = (await api.openCodeState()) as OpenCodeStatePayload;
        if (cancelled) return;
        const normalised = normaliseSessions((state?.sessions ?? {}) as Record<string, unknown>);
        setSessions(normalised);

        const bySession = (state?.messages_by_session ?? {}) as Record<string, SessionMessage[]>;
        setMessagesBySession(bySession);
        setSessionSources((state?.session_sources ?? {}) as Record<string, string>);
      } catch {
        // host unreachable
      }
    };

    load();
    const interval = setInterval(load, 5_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // ── WebSocket live stream ──────────────────────────────────────
  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/opencode/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      backoffRef.current = 1000;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'state') {
          const sessionsRaw = (msg as any)?.data?.sessions ?? {};
          const messagesRaw = (msg as any)?.data?.messages_by_session ?? {};
          const sourcesRaw = (msg as any)?.data?.session_sources ?? {};
          setSessions(normaliseSessions(sessionsRaw));
          setMessagesBySession(messagesRaw);
          setSessionSources(sourcesRaw);
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
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { sessions, messagesBySession, sessionSources, connected };
}
