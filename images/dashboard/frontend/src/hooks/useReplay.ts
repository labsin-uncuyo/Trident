import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  ReplayState,
  ReplayMetadata,
  ReplayEvent,
  WsReplayMessage,
} from '@/types';

const DEFAULT_REPLAY_STATE: ReplayState = {
  replayId: null,
  path: null,
  positionMs: 0,
  durationMs: 0,
  startTimeMs: 0,
  endTimeMs: 0,
  eventCount: 0,
  isPlaying: false,
  speed: 1,
  events: [],
  error: null,
};

interface UseReplayOptions {
  onLoad?: (metadata: ReplayMetadata) => void;
  onError?: (error: string) => void;
}

/**
 * Hook for managing replay playback state and WebSocket connection.
 *
 * @param replayId - The run ID to replay, or null to not load
 * @param pathOverride - Optional direct path to run directory
 * @param options - Callbacks for load and error events
 */
export function useReplay(
  replayId: string | null,
  pathOverride: string | null = null,
  options: UseReplayOptions = {}
) {
  const [state, setState] = useState<ReplayState>(DEFAULT_REPLAY_STATE);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const backoffRef = useRef(1000);
  const loadedRef = useRef(false);
  const eventsMapRef = useRef<Map<string, ReplayEvent>>(new Map());

  // Reset state when replayId changes
  useEffect(() => {
    if (replayId && replayId !== state.replayId) {
      loadedRef.current = false;
      eventsMapRef.current.clear();
      setState({
        ...DEFAULT_REPLAY_STATE,
        replayId,
        path: pathOverride,
      });
    }
  }, [replayId, pathOverride]);

  // Load replay metadata
  useEffect(() => {
    if (!replayId || loadedRef.current) return;

    const loadReplay = async () => {
      try {
        const response = await fetch('/api/replay/load', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...(pathOverride ? { path: pathOverride } : {}),
            ...(replayId ? { run_id: replayId } : {}),
          }),
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || error.error || 'Failed to load replay');
        }

        const metadata = (await response.json()) as ReplayMetadata;

        setState((s) => ({
          ...s,
          replayId: metadata.replay_id,
          path: metadata.path,
          positionMs: metadata.start_time_ms,
          durationMs: metadata.duration_ms,
          startTimeMs: metadata.start_time_ms,
          endTimeMs: metadata.end_time_ms,
          eventCount: metadata.event_count,
          events: [],  // Start empty, events will be streamed via WebSocket
        }));

        // Don't index initial events - they will come via WebSocket

        loadedRef.current = true;
        options?.onLoad?.(metadata);
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Unknown error';
        setState((s) => ({ ...s, error: errorMsg }));
        options?.onError?.(errorMsg);
      }
    };

    loadReplay();
  }, [replayId, pathOverride]);

  // WebSocket connection
  const connect = useCallback(() => {
    if (!replayId) return;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/replay/${replayId}/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      backoffRef.current = 1000;
      setState((s) => ({ ...s, error: null }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsReplayMessage;

        switch (msg.type) {
          case 'state': {
            setState((s) => ({
              ...s,
              positionMs: msg.position_ms,
              isPlaying: msg.playing,
              speed: msg.speed,
              durationMs: msg.duration_ms,
            }));
            break;
          }
          case 'events': {
            // Add new events, avoiding duplicates
            const newEvents: ReplayEvent[] = [];
            for (const event of msg.events) {
              const key = `${event.source_type}_${event.timestamp_ms}_${JSON.stringify(event).slice(0, 50)}`;
              if (!eventsMapRef.current.has(key)) {
                eventsMapRef.current.set(key, event);
                newEvents.push(event);
              }
            }

            if (newEvents.length > 0) {
              setState((s) => {
                const combined = [...s.events, ...newEvents];
                // Sort by timestamp
                combined.sort((a, b) => a.timestamp_ms - b.timestamp_ms);
                return { ...s, events: combined };
              });
            }
            break;
          }
          case 'playback_complete': {
            setState((s) => ({ ...s, isPlaying: false }));
            break;
          }
          case 'error': {
            setState((s) => ({ ...s, error: msg.message, isPlaying: false }));
            break;
          }
        }
      } catch {
        // Ignore JSON errors
      }
    };

    ws.onclose = () => {
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, 30000);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();
  }, [replayId]);

  useEffect(() => {
    if (replayId && loadedRef.current) {
      connect();
    }
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [replayId, loadedRef.current, connect]);

  // Control functions
  const play = useCallback((speed: number = state.speed) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'play', speed }));
    setState((s) => ({ ...s, isPlaying: true, speed }));
  }, [state.speed]);

  const pause = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'pause' }));
    setState((s) => ({ ...s, isPlaying: false }));
  }, []);

  const seek = useCallback((positionMs: number) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'seek', position_ms: positionMs }));
    setState((s) => ({ ...s, positionMs: positionMs }));
  }, []);

  const setSpeed = useCallback((speed: number) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'set_speed', speed }));
    setState((s) => ({ ...s, speed }));
  }, []);

  const togglePlay = useCallback(() => {
    if (state.isPlaying) {
      pause();
    } else {
      play(state.speed);
    }
  }, [state.isPlaying, state.speed, play, pause]);

  return {
    state,
    controls: {
      play,
      pause,
      seek,
      setSpeed,
      togglePlay,
    },
  };
}

/**
 * Hook for listing available replay runs.
 */
export function useReplayRuns() {
  const [runs, setRuns] = useState<Array<{ run_id: string; path: string; is_current: boolean; created: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        setLoading(true);
        const response = await fetch('/api/replay/runs');
        if (!response.ok) throw new Error('Failed to fetch runs');
        const data = await response.json();
        setRuns(data.runs || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
  }, []);

  return { runs, loading, error, refetch: () => fetch('/api/replay/runs').then(r => r.json().then(d => setRuns(d.runs || []))) };
}
