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
  openCodeSessions: (host: string) => api.get(`/opencode/${host}/sessions`),
  openCodeMessages: (host: string, sessionId: string) =>
    api.get(`/opencode/${host}/sessions/${sessionId}/messages`),

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
};
