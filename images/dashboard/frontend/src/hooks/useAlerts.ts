import { useState, useEffect, useRef, useCallback } from 'react';
import type { AlertEntry, WsAlertMessage } from '@/types';
import { api } from '@/api';

/**
 * Live alert stream with REST fallback for history.
 */
export function useAlerts() {
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  // Load existing alerts from REST
  useEffect(() => {
    api.alerts().then((data: any) => {
      if (data?.alerts) setAlerts(data.alerts);
    }).catch(() => {});
  }, []);

  const connect = useCallback(() => {
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

  return { alerts, connected };
}
