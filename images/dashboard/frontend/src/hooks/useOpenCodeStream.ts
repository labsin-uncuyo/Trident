import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type {
  SessionsMap,
  SessionMessage,
  OpenCodeStatePayload,
  ReplayEvent,
} from '@/types';
import { api } from '@/api';
import { useReplayContext } from '@/contexts/ReplayContext';

/** Normalise status values — upstream may return {type:"busy"} or "busy". */
function normaliseSessions(raw: Record<string, unknown>): SessionsMap {
  const out: SessionsMap = {};
  for (const [sid, val] of Object.entries(raw)) {
    out[sid] = typeof val === 'string' ? val : (val as any)?.type ?? 'unknown';
  }
  return out;
}

/** Map hosts to their expected source file patterns */
const HOST_SOURCE_PATTERNS: Record<string, string[]> = {
  compromised: [
    'coder56/',           // coder56 agent on compromised host
    'benign_agent/',      // db_admin on compromised host
    'defender/compromised/',  // defender on compromised host
  ],
  server: [
    'defender/server/',   // defender on server host
  ],
};

/** Convert replay events to OpenCode-like format */
function replayEventsToOpenCodeState(events: ReplayEvent[], host: string | undefined, positionMs: number, startTimeMs: number): {
  sessions: SessionsMap;
  messagesBySession: Record<string, SessionMessage[]>;
  sessionSources: Record<string, string>;
} {
  const sessions: SessionsMap = {};
  const sessionSources: Record<string, string> = {};

  // Get the source patterns for this host (if no host specified, include all)
  const sourcePatterns = host ? (HOST_SOURCE_PATTERNS[host] || []) : null;

  // Use the same time window as timeline: show events from startTimeMs to positionMs + 60 seconds
  // This ensures messages and timeline stay in sync
  const windowEndMs = positionMs + 60000; // 60 second look-ahead window

  console.log(`[useOpenCodeStream] host=${host}, events=${events.length}, startTimeMs=${startTimeMs}, positionMs=${positionMs}, windowEndMs=${windowEndMs}`);

  // First pass: collect all parts grouped by (sessionID → messageID)
  const bySession: Record<string, Map<string, { ts: number; parts: any[]; info: any }>> = {};

  let opencodeCount = 0;
  let filteredCount = 0;
  let stepFilteredCount = 0;

  for (const event of events) {
    // Filter by playback position window - show events in the time window
    if (event.timestamp_ms < startTimeMs || event.timestamp_ms > windowEndMs) {
      continue;
    }

    // Handle both opencode and timeline OPENCODE events
    const isOpencode = event.source_type === 'opencode' ||
                       (event.source_type === 'timeline' && event.level === 'OPENCODE');

    if (isOpencode) {
      opencodeCount++;

      // Filter by host if specified
      if (sourcePatterns) {
        const sourceFile = event.source_file || '';
        const matchesHost = sourcePatterns.some(pattern => sourceFile.includes(pattern));
        if (!matchesHost) {
          filteredCount++;
          continue;
        }
      }

      // Extract session_id from multiple possible locations
      const data = event.data as Record<string, unknown> | undefined;
      const sessionId = event.session_id ||
                        event.info?.sessionID ||
                        data?.sessionID ||
                        data?.session_id ||
                        event.exec ||
                        (event.info as any)?.exec ||
                        'default';
      const source = (event.source_file || '').split('/')[0] || 'unknown';

      // Set session status
      if (!sessions[sessionId]) {
        sessions[sessionId] = 'idle'; // Completed for replay
      }
      sessionSources[sessionId] = source;

      // Extract parts from event
      let parts: any[] | undefined = event.parts;
      if (!parts && Array.isArray(event.data?.part)) {
        parts = [event.data.part];
      } else if (!parts && event.data?.part) {
        parts = [event.data.part];
      }

      // Skip step-start/step-finish entries
      if (parts && parts.length === 1) {
        const partType = parts[0].type || parts[0].messageID ? parts[0].type : null;
        if (partType === 'step-start' || partType === 'step_start' || partType === 'step-finish' || partType === 'step_finish') {
          stepFilteredCount++;
          continue;
        }
      }

      // Build message with parts - group by messageID for proper reconstruction
      if (parts && parts.length > 0) {
        // Extract messageID from parts to group related parts together
        const messageID = parts[0]?.messageID || `${event.timestamp_ms}`;

        if (!bySession[sessionId]) {
          bySession[sessionId] = new Map();
        }

        const msgMap = bySession[sessionId];
        if (!msgMap.has(messageID)) {
          msgMap.set(messageID, { ts: event.timestamp_ms, parts: [], info: event.info || { sessionID: sessionId } });
        }
        msgMap.get(messageID)!.parts.push(...parts);
      }
    }
  }

  // Second pass: convert grouped parts into SessionMessage[]
  const messagesBySession: Record<string, SessionMessage[]> = {};
  for (const [sid, msgMap] of Object.entries(bySession)) {
    const msgs: SessionMessage[] = Array.from(msgMap.values())
      .sort((a, b) => a.ts - b.ts)
      .map(({ parts, info }) => ({
        info,
        parts,
      }));
    if (msgs.length > 0) messagesBySession[sid] = msgs;
  }

  const totalMessages = Object.values(messagesBySession).reduce((sum, arr) => sum + arr.length, 0);
  console.log(`[useOpenCodeStream] host=${host} stats: opencode=${opencodeCount}, filtered=${filteredCount}, stepFiltered=${stepFilteredCount}, totalMessages=${totalMessages}`);

  return { sessions, messagesBySession, sessionSources };
}

/**
 * Live OpenCode session stream for a host.
 * When a replay is active, returns data from the replay instead of live data.
 *
 * @param _host - Optional host filter ('compromised' | 'server')
 * @param timelineEntries - Optional timeline entries for message reconstruction (shared across agents)
 */
export function useOpenCodeStream(_host?: string, timelineEntries?: Array<{ level: string; data?: any }>) {
  const { replay } = useReplayContext();
  const [sessions, setSessions] = useState<SessionsMap>({});
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, SessionMessage[]>
  >({});
  const [sessionSources, setSessionSources] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);

  // Check if replay is active
  const isReplayActive = replay.replayId !== null;
  // Ref so onclose always sees the *current* replayId, avoiding stale-closure reconnects
  const replayIdRef = useRef<string | null>(replay.replayId);
  replayIdRef.current = replay.replayId;

  // Convert replay events to OpenCode format when replay is active
  // Filter by both host and current playback position
  const replayData = useMemo(() => {
    if (!isReplayActive) return null;
    return replayEventsToOpenCodeState(replay.events, _host, replay.positionMs, replay.startTimeMs);
  }, [isReplayActive, replay.events, _host, replay.positionMs, replay.startTimeMs]);

  // Reconstruct messages from timeline entries (for sessions that have ended)
  // This is computed once and shared across all agents
  const timelineMessages = useMemo(() => {
    if (!timelineEntries || timelineEntries.length === 0) return {};
    return reconstructTimelineMessages(timelineEntries, undefined);
  }, [timelineEntries]);

  // Update state from replay data
  useEffect(() => {
    if (replayData) {
      setSessions(replayData.sessions);
      setMessagesBySession(replayData.messagesBySession);
      setSessionSources(replayData.sessionSources);
      setConnected(true);
    } else if (replay.replayId !== null) {
      // Replay is active but no data yet
      setSessions({});
      setMessagesBySession({});
      setSessionSources({});
      setConnected(false);
    }
  }, [replayData, replay.replayId]);

  // ── REST load + periodic refresh (only when not in replay mode) ─────
  useEffect(() => {
    if (replay.replayId !== null) return; // Skip live data when replaying

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
  }, [replay.replayId]);

  // ── WebSocket live stream (only when not in replay mode) ─────────────
  const connect = useCallback(() => {
    // Don't connect if replay is active
    if (replay.replayId !== null) return;

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
      // Use ref (not closure) so we always read the *current* replayId.
      // Without this, loading a replay after the WS connected would cause a
      // spurious reconnect that overwrites replay session data with live data.
      if (replayIdRef.current === null) {
        setConnected(false);
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, 30000);
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };
    ws.onerror = () => ws.close();
  }, [replay.replayId]);

  useEffect(() => {
    // Only connect if not in replay mode
    if (replay.replayId === null) {
      connect();
    }
    return () => {
      clearTimeout(reconnectTimer.current);
      // Close WebSocket but only if it exists
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect, replay.replayId]);

  return { sessions, messagesBySession, sessionSources, connected, isReplayActive, timelineMessages };
}

/**
 * Reconstruct messages from timeline OPENCODE entries grouped by messageID.
 * This is used as a fallback when the API session has already ended.
 * Optimized version that processes entries in a single pass.
 */
export function reconstructTimelineMessages(
  entries: Array<{ level: string; data?: any }>,
  sessionFilter?: string,
): Record<string, SessionMessage[]> {
  // Group parts by (sessionID → messageID → ordered parts)
  const bySession: Record<string, Map<string, { ts: number; parts: any[] }>> = {};

  for (const e of entries) {
    if (e.level !== 'OPENCODE') continue;
    const d = e.data;
    if (!d) continue;

    const part = d.part;
    if (!part) continue;

    const sid = d.sessionID ?? d.session_id;
    const mid = part.messageID;

    // Filter by session if specified
    if (sessionFilter && sid !== sessionFilter) continue;

    if (!sid || !mid) continue;

    if (!bySession[sid]) bySession[sid] = new Map();
    const msgMap = bySession[sid];
    if (!msgMap.has(mid)) msgMap.set(mid, { ts: d.timestamp ?? 0, parts: [] });
    msgMap.get(mid)!.parts.push(part);
  }

  // Convert to SessionMessage[]
  const result: Record<string, SessionMessage[]> = {};
  for (const [sid, msgMap] of Object.entries(bySession)) {
    const msgs: SessionMessage[] = Array.from(msgMap.values())
      .sort((a, b) => a.ts - b.ts)
      .map(({ parts }) => ({
        info: { role: 'assistant' as const, sessionID: sid },
        parts,
      }));
    if (msgs.length > 0) result[sid] = msgs;
  }

  return result;
}
