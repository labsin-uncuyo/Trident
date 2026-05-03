const API_BASE = '/api';

export const api = {
  /** Generic JSON fetch */
  async get<T = unknown>(path: string): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return res.json();
  },

  /** Health */
  health: () => api.get('/health'),

  /** Topology */
  topology: () => api.get('/topology'),
  topologyTraffic: () => api.get<{ run_id: string | null; flows: unknown[]; edges: Record<string, { bytes: number; mb: number; label: string }> }>('/topology/traffic'),
  topologyAgents: () => api.get<{ agents: Record<string, string[]> }>('/topology/agents'),

  /** Containers */
  containers: () => api.get('/containers'),

  /** Runs */
  runs: () => api.get('/runs'),
  currentRun: () => api.get<{ run_id: string | null }>('/runs/current'),

  /** OpenCode */
  openCodeHosts: () => api.get('/opencode/hosts'),
  openCodeAgents: () => api.get('/opencode/agents'),
  openCodeState: () => api.get('/opencode/state'),
  openCodeSessions: () => api.get('/opencode/sessions'),
  openCodeMessages: (sessionId: string) =>
    api.get(`/opencode/sessions/${sessionId}/messages`),

  /** Alerts */
  alerts: (runId?: string) =>
    api.get(`/alerts${runId ? `?run_id=${runId}` : ''}`),

  /** PCAPs */
  pcaps: (runId?: string) =>
    api.get(`/pcaps${runId ? `?run_id=${runId}` : ''}`),

  /** Timeline */
  timelineAgents: () => api.get('/timeline/agents'),
  timeline: (agent: string, runId?: string) =>
    api.get(`/timeline/${agent}${runId ? `?run_id=${runId}` : ''}`),

  /** Replay */
  replayLoad: (path?: string, runId?: string) =>
    fetch('/api/replay/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(path ? { path } : {}),
        ...(runId ? { run_id: runId } : {}),
      }),
    }).then((r) => r.json()),
  replayRuns: () => api.get<{ runs: Array<{ run_id: string; path: string; is_current: boolean; created: string }> }>('/replay/runs'),
  replayEvents: (replayId: string, startMs?: number, endMs?: number) =>
    api.get(`/replay/${replayId}/events${startMs !== undefined ? `?start_ms=${startMs}` : ''}${endMs !== undefined ? `&end_ms=${endMs}` : ''}`),
};
