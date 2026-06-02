import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { TimelineEntry, WsTimelineMessage, ReplayEvent } from '@/types';
import { api } from '@/api';
import { useReplayContext } from '@/contexts/ReplayContext';

/** Map agent keys to their expected source file paths */
const AGENT_SOURCE_PATTERNS: Record<string, string[]> = {
  coder56: ['coder56/'],
  db_admin: ['benign_agent/db_admin'],
  soc_god_server: ['defender/server/'],
  soc_god_compromised: ['defender/compromised/'],
};

/** Convert replay events to TimelineEntry format */
function replayEventsToTimelineEntries(events: ReplayEvent[], agent: string, positionMs: number, startTimeMs: number): TimelineEntry[] {
  const entries: TimelineEntry[] = [];

  // Get the source patterns for this agent
  const sourcePatterns = AGENT_SOURCE_PATTERNS[agent] || [];

  // Calculate the window: show events from startTimeMs up to positionMs + 60 seconds
  // This ensures we see events that have just occurred and upcoming events
  const windowEndMs = positionMs + 60000; // 60 second look-ahead window

  console.log(`[useTimelineStream] ${agent}: Converting ${events.length} events, startTimeMs=${startTimeMs}, positionMs=${positionMs}, windowEndMs=${windowEndMs}, patterns=${JSON.stringify(sourcePatterns)}`);

  for (const event of events) {
    // Filter by playback position window - show events from start to current position + window
    if (event.timestamp_ms < startTimeMs || event.timestamp_ms > windowEndMs) {
      continue;
    }

    // Filter by source file path for the agent
    const sourceFile = event.source_file || '';

    // Check if this event belongs to the requested agent
    const matchesAgent = sourcePatterns.some(pattern => sourceFile.includes(pattern));
    if (!matchesAgent) {
      continue;
    }

    // Include all events that have meaningful timeline data
    // - timeline source_type: always include (these are from timeline JSONL files)
    // - opencode source_type with level: include if it has a level set
    // - alert source_type: include
    const isValidTimelineEvent =
      event.source_type === 'timeline' ||
      (event.source_type === 'opencode' && event.level) ||
      event.source_type === 'alert';

    if (!isValidTimelineEvent) {
      continue;
    }

    const entry: TimelineEntry = {
      ts: event.ts || new Date(event.timestamp_ms).toISOString(),
      level: (event.level as string | undefined) ||
             (event.source_type === 'alert' ? 'ALERT' : 'INFO'),
      msg: event.msg || '',
      exec: event.exec as string | undefined,
      data: event.data,
    };

    entries.push(entry);
  }

  console.log(`[useTimelineStream] ${agent}: Filtered to ${entries.length} entries`);

  // Filter out step_start/step_finish entries for cleaner display
  return entries.filter((e) => {
    const type = e.data?.type as string;
    return !(
      e.level === 'OPENCODE' &&
      (type === 'step_start' || type === 'step-start' || type === 'step_finish' || type === 'step-finish')
    );
  });
}

/**
 * Live timeline stream for an agent.
 * When a replay is active, returns data from the replay instead of live data.
 *
 * 1. REST poll every 3 s — always authoritative (reads the file on disk).
 * 2. WebSocket pushes new entries as they appear for lower latency.
 *    The WS backend polls the same file every 2 s and sends any new lines.
 *
 * The REST poll acts as safety-net so the UI is never stale for more
 * than a few seconds, even if the WS connection drops.
 */
export function useTimelineStream(agent: string) {
  const { replay } = useReplayContext();
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);
  // Ref so onclose always sees the *current* replayId, avoiding stale-closure reconnects
  const replayIdRef = useRef<string | null>(replay.replayId);

  // Keep ref in sync with state
  replayIdRef.current = replay.replayId;

  // Check if replay is active
  const isReplayActive = replay.replayId !== null;

  console.log(`[useTimelineStream] ${agent} render: replayId=${replay.replayId}, events.length=${replay.events.length}, startTimeMs=${replay.startTimeMs}, positionMs=${replay.positionMs}`);

  // Convert replay events to timeline format when replay is active
  // Filter by both agent and current playback position
  const replayEntries = useMemo(() => {
    if (!isReplayActive) return null;
    return replayEventsToTimelineEntries(replay.events, agent, replay.positionMs, replay.startTimeMs);
  }, [isReplayActive, replay.events, agent, replay.positionMs, replay.startTimeMs]);

  // Update state from replay data
  useEffect(() => {
    console.log(`[useTimelineStream] ${agent} effect: replayId=${replay.replayId}, replayEntries=${replayEntries?.length ?? null}`);
    if (replay.replayId !== null && replayEntries) {
      setEntries(replayEntries);
      setConnected(true);
    }
  }, [replayEntries, replay.replayId, agent]);

  // ── REST poll every 3 s (only when not in replay mode) ─────────────
  useEffect(() => {
    if (replay.replayId !== null) return; // Skip live data when replaying

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
  }, [agent, replay.replayId]);

  // ── WebSocket live stream (only when not in replay mode) ─────────────
  const connect = useCallback(() => {
    // Don't connect if replay is active
    if (replay.replayId !== null) {
      console.log(`[useTimelineStream] ${agent}: Skipping WebSocket, replay is active`);
      return;
    }

    console.log(`[useTimelineStream] ${agent}: Connecting WebSocket`);
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
      // Use ref (not closure) so we always read the *current* replayId.
      // Without this, loading a replay after the WS connected would leave
      // replayId=null in the closure, causing a spurious reconnect that then
      // overwrites replay state with live data.
      if (replayIdRef.current === null) {
        setConnected(false);
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, 30000);
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };
    ws.onerror = () => ws.close();
  }, [agent, replay.replayId]);

  useEffect(() => {
    // Only connect if not in replay mode
    if (replay.replayId === null) {
      connect();
    }
    return () => {
      clearTimeout(reconnectTimer.current);
      // Close WebSocket but only if it's open or connecting
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect, replay.replayId]);

  return { entries, connected, isReplayActive };
}
