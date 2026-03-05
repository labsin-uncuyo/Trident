import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Cpu, ArrowRight, Radio } from 'lucide-react';
import { useOpenCodeStream } from '@/hooks/useOpenCodeStream';
import { useTimelineStream } from '@/hooks/useTimelineStream';
import type { SessionsMap, TimelineEntry } from '@/types';

const LEVEL_STYLES: Record<string, string> = {
  INIT: 'text-blue-400',
  OPENCODE: 'text-purple-400',
  ERROR: 'text-red-400',
  WARNING: 'text-amber-400',
  INFO: 'text-green-400',
  DEBUG: 'text-trident-muted',
};

function TimelineEntryRow({ entry }: { entry: TimelineEntry }) {
  const [expanded, setExpanded] = useState(false);
  const levelColor = LEVEL_STYLES[entry.level] ?? 'text-trident-muted';
  const rawOcType = (entry.data as any)?.type;
  const ocType = typeof rawOcType === 'string' ? rawOcType : undefined;
  const subLabel = ocType ? ` · ${ocType}` : '';

  return (
    <div
      className="cursor-pointer border-b border-trident-border/40 px-3 py-1.5 hover:bg-white/5"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-start gap-2 text-xs">
        <span className="w-16 flex-shrink-0 font-mono text-[10px] text-trident-muted">
          {entry.ts.slice(11, 19)}
        </span>
        <span className={`w-20 flex-shrink-0 font-mono font-bold ${levelColor}`}>
          {entry.level}{subLabel}
        </span>
        <span className="truncate text-trident-text">{typeof entry.msg === 'string' ? entry.msg : JSON.stringify(entry.msg)}</span>
      </div>
      {expanded && entry.data && (
        <pre className="terminal-output mt-1 max-h-40 overflow-auto text-[10px] text-trident-muted">
          {JSON.stringify(entry.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

const HOSTS = ['compromised', 'server'] as const;

const TIMELINE_AGENTS: Array<{ key: string; label: string; desc: string; color: string }> = [
  {
    key: 'coder56',
    label: 'coder56',
    desc: 'Red-team attacker — recon, exploitation, persistence',
    color: 'text-red-400',
  },
  {
    key: 'db_admin',
    label: 'db_admin',
    desc: 'Benign DBA persona "John Scott" — routine DB tasks',
    color: 'text-green-400',
  },
  {
    key: 'soc_god_server',
    label: 'soc_god · server',
    desc: 'Autonomous defensive subsystem — threat analysis & remediation (server)',
    color: 'text-sky-400',
  },
  {
    key: 'soc_god_compromised',
    label: 'soc_god · compromised',
    desc: 'Autonomous defensive subsystem — threat analysis & remediation (compromised)',
    color: 'text-cyan-400',
  },
];

function TimelineAgentPanel({ agentKey, label, desc, color }: {
  agentKey: string;
  label: string;
  desc: string;
  color: string;
}) {
  const { entries, connected } = useTimelineStream(agentKey);
  const recent = entries.slice(-200);
  const lastEntry = recent[recent.length - 1];

  return (
    <div className="card flex flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio size={16} className={color} />
          <h3 className={`font-heading text-lg font-bold ${color}`}>{label}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`badge ${connected ? 'badge-success' : 'badge-danger'}`}>
            {connected ? 'Live' : 'Disconnected'}
          </span>
        </div>
      </div>

      <p className="mb-3 text-xs text-trident-muted">{desc}</p>

      <div className="mb-3 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-white">{entries.length}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Events</p>
        </div>
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className={`truncate text-sm font-bold ${lastEntry ? LEVEL_STYLES[lastEntry.level] ?? 'text-trident-muted' : 'text-trident-muted'}`}>
            {lastEntry?.level ?? '—'}
          </p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Last Level</p>
        </div>
      </div>

      {entries.length === 0 ? (
        <p className="py-4 text-center text-sm text-trident-muted">
          {connected ? 'Waiting for events…' : 'No events yet'}
        </p>
      ) : (
        <div className="flex-1 overflow-auto rounded-lg border border-trident-border bg-black/20 max-h-64">
          {recent.map((e, i) => (
            <TimelineEntryRow key={i} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function HostPanel({ host }: { host: string }) {
  const { sessions, messagesBySession, connected } = useOpenCodeStream(host);

  const sessionEntries = Object.entries(sessions);
  const activeCount = sessionEntries.filter(([_, s]) => {
    const st = typeof s === 'string' ? s : (s as any)?.type;
    return st === 'busy' || st === 'running';
  }).length;

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu size={18} className="text-trident-accent" />
          <h3 className="font-heading text-lg font-bold text-white capitalize">{host}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`badge ${connected ? 'badge-success' : 'badge-danger'}`}>
            {connected ? 'Live' : 'Disconnected'}
          </span>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-white">{sessionEntries.length}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Sessions</p>
        </div>
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-green-400">{activeCount}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Active</p>
        </div>
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-trident-muted">
            {Object.values(messagesBySession).reduce((a, b) => a + b.length, 0)}
          </p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Messages</p>
        </div>
      </div>

      {sessionEntries.length === 0 ? (
        <p className="py-4 text-center text-sm text-trident-muted">No active sessions</p>
      ) : (
        <div className="space-y-2">
          {sessionEntries.map(([sid, rawStatus]) => {
            // Status may arrive as a string or as {type: "busy"}
            const statusStr = typeof rawStatus === 'string'
              ? rawStatus
              : (rawStatus as any)?.type ?? 'unknown';
            const msgs = messagesBySession[sid] || [];
            const lastMsg = msgs[msgs.length - 1];
            const rawLastText = lastMsg?.parts?.find((p) => p.type === 'text')?.text;
            const lastText = typeof rawLastText === 'string' ? rawLastText : '';

            return (
              <Link
                key={sid}
                to={`/agents/${host}/${sid}`}
                className="block rounded-lg border border-trident-border p-3 transition-colors hover:border-trident-accent/50 hover:bg-trident-accent/5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-trident-text">
                    {sid.slice(0, 12)}…
                  </span>
                  <span
                    className={`badge ${
                      statusStr === 'busy' || statusStr === 'running'
                        ? 'badge-warning'
                        : statusStr === 'idle'
                        ? 'badge-success'
                        : 'badge-muted'
                    }`}
                  >
                    {statusStr}
                  </span>
                </div>
                {lastText && (
                  <p className="mt-1 truncate text-xs text-trident-muted">
                    {lastText.slice(0, 120)}
                  </p>
                )}
                <div className="mt-1 flex items-center justify-between text-[10px] text-trident-muted">
                  <span>{msgs.length} messages</span>
                  <ArrowRight size={10} />
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AgentsPage() {
  return (
    <div className="flex h-full flex-col gap-6 overflow-auto">
      {/* ── Timeline agents (coder56, db_admin) ── */}
      <div>
        <h2 className="font-heading text-2xl font-bold text-white">Agents</h2>
        <p className="mb-4 text-sm text-trident-muted">
          Live event timeline from auto-responder agents
        </p>
        <div className="grid grid-cols-2 gap-6">
          {TIMELINE_AGENTS.map((a) => (
            <TimelineAgentPanel
              key={a.key}
              agentKey={a.key}
              label={a.label}
              desc={a.desc}
              color={a.color}
            />
          ))}
        </div>
      </div>

      {/* ── OpenCode sessions (compromised / server) ── */}
      <div>
        <h2 className="font-heading text-xl font-bold text-white">OpenCode Sessions</h2>
        <p className="mb-4 text-sm text-trident-muted">
          Live OpenCode sessions across compromised host and server
        </p>
        <div className="grid grid-cols-2 gap-6">
          {HOSTS.map((host) => (
            <HostPanel key={host} host={host} />
          ))}
        </div>
      </div>
    </div>
  );
}
