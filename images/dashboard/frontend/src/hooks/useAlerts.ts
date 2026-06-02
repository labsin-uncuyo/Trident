import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { AlertEntry, WsAlertMessage, ReplayEvent } from '@/types';
import { api } from '@/api';
import { useReplayContext } from '@/contexts/ReplayContext';

/** Convert replay events to AlertEntry format */
function replayEventsToAlerts(events: ReplayEvent[], positionMs: number): AlertEntry[] {
  const alerts: AlertEntry[] = [];

  for (const event of events) {
    // Only include alert events and filter by position
    if (event.source_type === 'alert' && event.timestamp_ms <= positionMs) {
      alerts.push({
        timestamp: event.ts || new Date(event.timestamp_ms).toISOString(),
        ...(event.data as object),
      } as AlertEntry);
    }
  }

  return alerts;
}

/**
 * Live alert stream with REST fallback for history.
 * When replay is active, shows alerts from replay data.
 */
export function useAlerts() {
  const { replay } = useReplayContext();
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const isReplayActive = replay.replayId !== null;
  // Ref so onclose always sees the *current* replayId, avoiding stale-closure reconnects
  const replayIdRef = useRef<string | null>(replay.replayId);
  replayIdRef.current = replay.replayId;

  // Convert replay events to alerts when replay is active
  const replayAlerts = useMemo(() => {
    if (!isReplayActive) return null;
    return replayEventsToAlerts(replay.events, replay.positionMs);
  }, [isReplayActive, replay.events, replay.positionMs]);

  // Update state from replay data
  useEffect(() => {
    if (isReplayActive && replayAlerts) {
      setAlerts(replayAlerts);
      setConnected(true);
    }
  }, [replayAlerts, isReplayActive]);

  // Load existing alerts from REST (only when not in replay mode)
  useEffect(() => {
    if (isReplayActive) return;

    api.alerts().then((data: any) => {
      if (data?.alerts) setAlerts(data.alerts);
    }).catch(() => {});
  }, [isReplayActive]);

  const connect = useCallback(() => {
    // Don't connect if replay is active
    if (replay.replayId !== null) return;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/alerts/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onmessage = (event) => {
      try {
        const msg: WsAlertMessage = JSON.parse(event.data);
        if (msg.type === 'alert') {
          setAlerts((prev) => [...prev, msg.data]);
        }
      } catch {}
    };
    ws.onclose = () => {
      // Use ref (not closure) so we always read the *current* replayId.
      // Without this, loading a replay after the WS connected would cause a
      // spurious reconnect that overwrites replay alerts with live data.
      if (replayIdRef.current === null) {
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3000);
      }
    };
    ws.onerror = () => ws.close();
  }, [replay.replayId]);

  useEffect(() => {
    if (!isReplayActive) {
      connect();
    }
    return () => {
      clearTimeout(reconnectTimer.current);
      // Close WebSocket but only if it exists
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect, isReplayActive]);

  return { alerts, connected, isReplayActive };
}
