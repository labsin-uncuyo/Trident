import { useState, useEffect, useRef, useCallback } from 'react';
import type { ContainerInfo, WsContainersMessage } from '@/types';
import { api } from '@/api';

/**
 * Hook that provides live container status via WebSocket
 * with REST fallback for initial load.
 */
export function useContainers() {
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  // Initial REST load
  useEffect(() => {
    api.containers().then((data) => setContainers(data as ContainerInfo[])).catch(() => {});
  }, []);

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/containers/ws`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onmessage = (event) => {
      try {
        const msg: WsContainersMessage = JSON.parse(event.data);
        if (msg.type === 'containers') {
          setContainers(msg.data);
        }
      } catch {}
    };
    ws.onclose = () => {
      setConnected(false);
      reconnectTimer.current = setTimeout(connect, 3000);
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

  return { containers, connected };
}
