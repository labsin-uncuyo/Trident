import { useAlerts } from '@/hooks/useAlerts';
import { useEffect, useRef, useState } from 'react';
import {
  ShieldAlert,
  Filter,
  ArrowDown,
  Clock,
  AlertTriangle,
} from 'lucide-react';

export function AlertsPage() {
  const { alerts, connected } = useAlerts();
  const [filter, setFilter] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const filtered = filter
    ? alerts.filter((a) => JSON.stringify(a).toLowerCase().includes(filter.toLowerCase()))
    : alerts;

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [filtered.length, autoScroll]);

  // Extract severity/type from alert data (varies by SLIPS format)
  function getSeverity(alert: Record<string, unknown>): string {
    const data = (alert.data ?? alert) as Record<string, unknown>;
    if (typeof data.threat_level === 'string') return data.threat_level;
    if (typeof data.confidence === 'number') {
      if (data.confidence > 0.8) return 'high';
      if (data.confidence > 0.5) return 'medium';
      return 'low';
    }
    return 'info';
  }

  function sevBadge(sev: string) {
    switch (sev) {
      case 'high':
      case 'critical':
        return 'badge-danger';
      case 'medium':
        return 'badge-warning';
      case 'low':
        return 'badge-info';
      default:
        return 'badge-muted';
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="font-heading text-2xl font-bold text-white">Alerts</h2>
          <p className="text-sm text-trident-muted">
            SLIPS IDS alerts — {alerts.length} total
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`badge ${connected ? 'badge-success' : 'badge-danger'}`}>
            {connected ? 'Live' : 'Offline'}
          </span>
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`btn-ghost text-xs ${autoScroll ? 'text-trident-accent' : ''}`}
          >
            <ArrowDown size={14} className="mr-1" />
            {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          </button>
        </div>
      </div>

      {/* Filter */}
      <div className="mb-4 flex items-center gap-2">
        <Filter size={14} className="text-trident-muted" />
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter alerts…"
          className="flex-1 rounded-lg border border-trident-border bg-trident-surface px-3 py-2 text-sm text-trident-text placeholder:text-trident-muted focus:border-trident-accent focus:outline-none"
        />
        <span className="text-xs text-trident-muted">
          {filtered.length} / {alerts.length}
        </span>
      </div>

      {/* Alert list */}
      <div className="flex-1 space-y-2 overflow-auto">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-trident-muted">
            <ShieldAlert size={48} className="mb-4 opacity-30" />
            <p className="text-sm">No alerts yet</p>
            <p className="text-xs">Alerts will appear here when SLIPS detects threats</p>
          </div>
        ) : (
          filtered.map((alert, idx) => {
            const data = (alert.data ?? alert) as Record<string, unknown>;
            const sev = getSeverity(alert);
            const ts = (alert.timestamp ?? data.timestamp ?? '') as string;
            const description =
              (data.description as string) ??
              (data.evidence as string) ??
              (data.msg as string) ??
              JSON.stringify(data).slice(0, 200);

            return (
              <div
                key={idx}
                className="card flex items-start gap-3 border-l-4"
                style={{
                  borderLeftColor:
                    sev === 'high' || sev === 'critical'
                      ? '#ef4444'
                      : sev === 'medium'
                      ? '#f59e0b'
                      : '#3b82f6',
                }}
              >
                <AlertTriangle
                  size={16}
                  className={`mt-0.5 flex-shrink-0 ${
                    sev === 'high' || sev === 'critical'
                      ? 'text-red-400'
                      : sev === 'medium'
                      ? 'text-yellow-400'
                      : 'text-blue-400'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${sevBadge(sev)}`}>{sev}</span>
                    {data.type != null && (
                      <span className="badge badge-muted">{String(data.type)}</span>
                    )}
                    {data.source_ip != null && (
                      <span className="font-mono text-[10px] text-trident-muted">
                        {String(data.source_ip)}
                      </span>
                    )}
                    {ts && (
                      <span className="ml-auto flex items-center gap-1 text-[10px] text-trident-muted">
                        <Clock size={10} />
                        {new Date(ts).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-trident-text leading-relaxed">{description}</p>
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
