/* ── Container status types ─────────────────────────────────────── */

export type ContainerState =
  | 'running'
  | 'stopped'
  | 'restarting'
  | 'paused'
  | 'exited'
  | 'dead'
  | 'unknown';

export interface ContainerInfo {
  id: string;
  name: string;
  image: string;
  state: ContainerState;
  status: string;
  health: string | null;
  networks: string[];
  ip_addresses: Record<string, string>;
}

/* ── Topology ──────────────────────────────────────────────────── */

export type NodeType = 'router' | 'server' | 'host' | 'attacker' | 'defender' | 'dashboard';

export interface TopologyNode {
  id: string;
  label: string;
  type: NodeType;
  ips: string[];
  networks: string[];
  services: string[];
  container: string;
  state: ContainerState;
  position: { x: number; y: number };
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  animated: boolean;
}

export interface TopologyData {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

/* ── OpenCode ──────────────────────────────────────────────────── */

export interface MessagePart {
  type: string;
  text?: string;
  tool?: string;
  time?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SessionMessage {
  info?: {
    sessionID?: string;
    role?: string;
    time?: { created?: number; completed?: number };
    tokens?: { input?: number; output?: number; reasoning?: number };
    cost?: number;
    finish?: string;
  };
  parts: MessagePart[];
}

export interface SessionsMap {
  [sessionId: string]: string; // status
}

/* ── Alerts ────────────────────────────────────────────────────── */

export interface AlertEntry {
  timestamp?: string;
  run_id?: string;
  [key: string]: unknown;
}

/* ── PCAPs ─────────────────────────────────────────────────────── */

export interface PcapFile {
  filename: string;
  path: string;
  size_bytes: number;
  modified: string;
}

/* ── Runs ──────────────────────────────────────────────────────── */

export interface RunInfo {
  run_id: string;
  path: string;
  is_current: boolean;
  created: string;
  has_pcaps: boolean;
  has_alerts: boolean;
}

/* ── Timeline ──────────────────────────────────────────────────── */

export interface TimelineEntry {
  ts: string;
  level: string;
  msg: string;
  exec?: string;
  data?: Record<string, unknown>;
}

/* ── Health ─────────────────────────────────────────────────────── */

export interface ServiceHealth {
  name: string;
  healthy: boolean;
  detail: string;
}

export interface HealthResponse {
  status: string;
  run_id: string | null;
  timestamp: string;
  services: ServiceHealth[];
}

/* ── WebSocket message types ───────────────────────────────────── */

export interface WsContainersMessage {
  type: 'containers';
  data: ContainerInfo[];
}

export interface WsSessionsMessage {
  type: 'sessions';
  host: string;
  data: SessionsMap;
}

export interface WsMessagesMessage {
  type: 'messages';
  host: string;
  session_id: string;
  data: SessionMessage[];
  total: number;
}

export interface OpenCodeStatePayload {
  run_id: string | null;
  updated_at: string;
  sessions: SessionsMap;
  session_sources?: Record<string, string>;
  messages_by_session: Record<string, SessionMessage[]>;
}

export interface WsAlertMessage {
  type: 'alert';
  run_id: string;
  data: AlertEntry;
}

export interface WsTimelineMessage {
  type: 'timeline';
  agent: string;
  data: TimelineEntry;
}
