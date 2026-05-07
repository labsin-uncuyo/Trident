import { createContext, useContext, useState, useCallback, useRef, ReactNode } from 'react';
import type { ReplayEvent, ReplayMetadata } from '@/types';

interface ReplayState {
  replayId: string | null;
  path: string | null;
  positionMs: number;
  durationMs: number;
  startTimeMs: number;
  endTimeMs: number;
  eventCount: number;
  isPlaying: boolean;
  speed: number;
  events: ReplayEvent[];
  metadata: ReplayMetadata | null;
}

interface ReplayContextType {
  replay: ReplayState;
  controls: {
    loadReplay: (path: string, runId?: string) => Promise<void>;
    play: (speed?: number) => void;
    pause: () => void;
    seek: (positionMs: number) => void;
    setSpeed: (speed: number) => void;
    togglePlay: () => void;
    stop: () => void;
  };
  isLoading: boolean;
  error: string | null;
}

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
  metadata: null,
};

const ReplayContext = createContext<ReplayContextType | undefined>(undefined);

export function ReplayProvider({ children }: { children: ReactNode }) {
  const [replay, setReplay] = useState<ReplayState>(DEFAULT_REPLAY_STATE);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pendingPlayRef = useRef<{ speed: number } | null>(null);
  const activeReplayIdRef = useRef<string | null>(null);

  const loadReplay = useCallback(async (path: string, runId?: string) => {
    setIsLoading(true);
    setError(null);
    activeReplayIdRef.current = null;

    // Stop any existing replay
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    try {
      const response = await fetch('/api/replay/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(path ? { path } : {}),
          ...(runId ? { run_id: runId } : {}),
        }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || err.error || 'Failed to load replay');
      }

      const metadata = (await response.json()) as ReplayMetadata;
      activeReplayIdRef.current = metadata.replay_id;

      setReplay({
        replayId: metadata.replay_id,
        path: metadata.path,
        positionMs: metadata.start_time_ms,
        durationMs: metadata.duration_ms,
        startTimeMs: metadata.start_time_ms,
        endTimeMs: metadata.end_time_ms,
        eventCount: metadata.event_count,
        isPlaying: false,
        speed: 1,
        events: [],  // Start empty, events will be streamed via WebSocket
        metadata,
      });

      // Connect to WebSocket for playback control
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}/api/replay/${metadata.replay_id}/ws`;
      console.log('[ReplayContext] Connecting to WebSocket:', url);

      // Add timeout to detect if connection fails
      const connectionTimeout = setTimeout(() => {
        if (wsRef.current?.readyState === WebSocket.CONNECTING) {
          console.error('[ReplayContext] WebSocket connection timeout - still connecting after 5 seconds');
          console.log('[ReplayContext] URL was:', url);
          console.log('[ReplayContext] This might be a CORS or proxy issue');
        }
      }, 5000);

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        clearTimeout(connectionTimeout);
        console.log('[ReplayContext] WebSocket connected');
        // If there's a pending play command, execute it now
        if (pendingPlayRef.current !== null) {
          console.log('[ReplayContext] Executing pending play command');
          ws.send(JSON.stringify({ type: 'play', speed: pendingPlayRef.current.speed }));
          setReplay((prev) => ({ ...prev, isPlaying: true, speed: pendingPlayRef.current!.speed }));
          pendingPlayRef.current = null;
        }
      };

      ws.onerror = (e) => {
        clearTimeout(connectionTimeout);
        console.error('[ReplayContext] WebSocket error:', e);
      };

      ws.onclose = (e) => {
        clearTimeout(connectionTimeout);
        console.log('[ReplayContext] WebSocket closed:', e.code, e.reason);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          console.log('[ReplayContext] WebSocket message:', msg.type, msg);

          const msgReplayId = msg.replay_id as string | undefined;
          if (msgReplayId && activeReplayIdRef.current && msgReplayId !== activeReplayIdRef.current) {
            console.log('[ReplayContext] Ignoring message for replay:', msgReplayId);
            return;
          }
          if (msgReplayId && !activeReplayIdRef.current) {
            return;
          }

          switch (msg.type) {
            case 'state':
              console.log('[ReplayContext] State update:', msg.position_ms, 'playing:', msg.playing);
              setReplay((prev) => ({
                ...prev,
                positionMs: msg.position_ms,
                isPlaying: msg.playing,
                speed: msg.speed,
              }));
              break;
            case 'events':
              console.log('[ReplayContext] Received', msg.events?.length, 'events');
              setReplay((prev) => {
                const newEvents = msg.events.filter(
                  (ne: ReplayEvent) => !prev.events.some(
                    (ee) => ee.timestamp_ms === ne.timestamp_ms &&
                           ee.source_type === ne.source_type &&
                           JSON.stringify(ee).slice(0, 100) === JSON.stringify(ne).slice(0, 100)
                  )
                );
                const combined = [...prev.events, ...newEvents];
                combined.sort((a, b) => a.timestamp_ms - b.timestamp_ms);
                console.log('[ReplayContext] Total events after update:', combined.length);
                return { ...prev, events: combined };
              });
              break;
            case 'playback_complete':
              console.log('[ReplayContext] Playback complete');
              setReplay((prev) => ({ ...prev, isPlaying: false }));
              break;
            case 'error':
              console.error('[ReplayContext] Error:', msg.message);
              setError(msg.message);
              setReplay((prev) => ({ ...prev, isPlaying: false }));
              break;
          }
        } catch (e) {
          console.error('Failed to parse replay WebSocket message', e);
        }
      };

    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      setReplay(DEFAULT_REPLAY_STATE);
      activeReplayIdRef.current = null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const play = useCallback((speed?: number) => {
    const newSpeed = speed ?? replay.speed;
    console.log('[ReplayContext] play called, wsRef.current:', wsRef.current, 'readyState:', wsRef.current?.readyState);

    if (!wsRef.current) {
      console.error('[ReplayContext] Cannot play - no WebSocket');
      return;
    }

    if (wsRef.current.readyState === WebSocket.OPEN) {
      console.log('[ReplayContext] Sending play command, speed:', newSpeed);
      wsRef.current.send(JSON.stringify({ type: 'play', speed: newSpeed }));
      setReplay((prev) => ({ ...prev, isPlaying: true, speed: newSpeed }));
    } else if (wsRef.current.readyState === WebSocket.CONNECTING) {
      // WebSocket is still connecting, queue the play command
      console.log('[ReplayContext] WebSocket connecting, queueing play command');
      pendingPlayRef.current = { speed: newSpeed };
    } else {
      console.error('[ReplayContext] Cannot play - WebSocket not connected, state:', wsRef.current.readyState);
    }
  }, [replay.speed]);

  const pause = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'pause' }));
    setReplay((prev) => ({ ...prev, isPlaying: false }));
  }, []);

  const seek = useCallback((positionMs: number) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'seek', position_ms: positionMs }));
    setReplay((prev) => ({ ...prev, positionMs }));
  }, []);

  const setSpeed = useCallback((speed: number) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'set_speed', speed }));
    setReplay((prev) => ({ ...prev, speed }));
  }, []);

  const togglePlay = useCallback(() => {
    if (replay.isPlaying) {
      pause();
    } else {
      play(replay.speed);
    }
  }, [replay.isPlaying, replay.speed, play, pause]);

  const stop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    pendingPlayRef.current = null;
    activeReplayIdRef.current = null;
    setReplay(DEFAULT_REPLAY_STATE);
    setError(null);
  }, []);

  return (
    <ReplayContext.Provider
      value={{
        replay,
        controls: { loadReplay, play, pause, seek, setSpeed, togglePlay, stop },
        isLoading,
        error,
      }}
    >
      {children}
    </ReplayContext.Provider>
  );
}

export function useReplayContext() {
  const context = useContext(ReplayContext);
  if (!context) {
    throw new Error('useReplayContext must be used within ReplayProvider');
  }
  return context;
}

// Helper hook to get filtered events by time range
export function useReplayEvents(endMs?: number) {
  const { replay } = useReplayContext();
  const currentTime = endMs ?? replay.positionMs;

  return replay.events.filter((e) => e.timestamp_ms <= currentTime);
}
