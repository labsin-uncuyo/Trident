import { useState, useMemo, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Cpu, ArrowRight, Radio, MessageSquare } from 'lucide-react';
import { useOpenCodeStream } from '@/hooks/useOpenCodeStream';
import { useTimelineStream } from '@/hooks/useTimelineStream';
import { SessionStream } from '@/components/SessionStream';
import { api } from '@/api';
import type { SessionsMap, SessionMessage, TimelineEntry } from '@/types';

const LEVEL_STYLES: Record<string, string> = {
  INIT: 'text-blue-400',
  OPENCODE: 'text-purple-400',
  ERROR: 'text-red-400',
  WARNING: 'text-amber-400',
  INFO: 'text-green-400',
  DEBUG: 'text-trident-muted',
};

function ocEntrySummary(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  const type = d.type as string;
  if (type === 'step_start' || type === 'step-start' || type === 'step_finish' || type === 'step-finish') return null; // hidden
  const part = d.part as Record<string, unknown> | undefined;
  if (type === 'tool_use' && part) {
    const tool = part.tool as string | undefined;
    const state = part.state as Record<string, unknown> | undefined;
    const input = state?.input as Record<string, unknown> | undefined;
    const desc = (input?.description ?? input?.command ?? input?.query ?? input?.content ?? input?.path ?? '') as string;
    return tool ? `${tool}${desc ? ` · ${desc.replace(/\n/g, ' ').slice(0, 100)}` : ''}` : null;
  }
  if (type === 'text' && part) {
    const text = part.text as string | undefined;
    if (text) return text.replace(/\n/g, ' ').slice(0, 120);
  }
  return null;
}

function TimelineEntryRow({ entry }: { entry: TimelineEntry }) {
  const [expanded, setExpanded] = useState(false);
  const levelColor = LEVEL_STYLES[entry.level] ?? 'text-trident-muted';
  const data = entry.data as Record<string, unknown> | undefined;
  const ocType = data?.type as string | undefined;

  // Hide step_start / step_finish rows entirely
  if (entry.level === 'OPENCODE' && (ocType === 'step_start' || ocType === 'step-start' || ocType === 'step_finish' || ocType === 'step-finish')) {
    return null;
  }

  const summary = entry.level === 'OPENCODE' ? ocEntrySummary(entry.data) : null;
  const displayMsg = summary ?? (typeof entry.msg === 'string' ? entry.msg : JSON.stringify(entry.msg));
  const levelLabel = entry.level === 'OPENCODE' && ocType ? ocType.replace(/_/g, ' ') : entry.level;

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
          {levelLabel}
        </span>
        <span className="truncate text-trident-text">{displayMsg}</span>
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

const TIMELINE_AGENTS: Array<{ key: string; label: string; desc: string; color: string; host: string }> = [
  {
    key: 'coder56',
    label: 'coder56',
    desc: 'Red-team attacker — recon, exploitation, persistence',
    color: 'text-red-400',
    host: 'compromised',
  },
  {
    key: 'db_admin',
    label: 'db_admin',
    desc: 'Benign DBA persona "John Scott" — routine DB tasks',
    color: 'text-green-400',
    host: 'compromised',
  },
  {
    key: 'soc_god_server',
    label: 'soc_god · server',
    desc: 'Autonomous defensive subsystem — threat analysis & remediation (server)',
    color: 'text-sky-400',
    host: 'server',
  },
  {
    key: 'soc_god_compromised',
    label: 'soc_god · compromised',
    desc: 'Autonomous defensive subsystem — threat analysis & remediation (compromised)',
    color: 'text-cyan-400',
    host: 'compromised',
  },
];

function TimelineAgentPanel({ agentKey, label, desc, color, host, messagesBySession }: {
  agentKey: string;
  label: string;
  desc: string;
  color: string;
  host: string;
  messagesBySession: Record<string, SessionMessage[]>;
}) {
  const { entries, connected } = useTimelineStream(agentKey);
  const recent = entries.slice(-200);
  const lastEntry = recent[recent.length - 1];

  // Extra messages fetched directly for sessions not in the shared stream cache
  const [extraMessages, setExtraMessages] = useState<Record<string, SessionMessage[]>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  // Extract session_id(s) from timeline SESSION entries or OPENCODE data.sessionID
  const sessionIds = useMemo(() => {
    const ids: string[] = [];
    for (const e of entries) {
      const d = e.data as any;
      if (e.level === 'SESSION') {
        const sid = d?.session_id;
        if (typeof sid === 'string' && !ids.includes(sid)) ids.push(sid);
      }
      if (e.level === 'OPENCODE') {
        const sid = d?.sessionID ?? d?.session_id;
        if (typeof sid === 'string' && !ids.includes(sid)) ids.push(sid);
      }
    }
    return ids;
  }, [entries]);

  // Reconstruct messages from timeline OPENCODE entries grouped by messageID.
  // This is used as a fallback when the API session has already ended and returns no data.
  const timelineMessages = useMemo((): Record<string, SessionMessage[]> => {
    // Group parts by (sessionID → messageID → ordered parts)
    const bySession: Record<string, Map<string, { ts: number; parts: any[] }>> = {};
    for (const e of entries) {
      if (e.level !== 'OPENCODE') continue;
      const d = e.data as any;
      const part = d?.part;
      if (!part) continue;
      const sid = d?.sessionID ?? d?.session_id;
      const mid = part?.messageID;
      if (!sid || !mid) continue;
      if (!bySession[sid]) bySession[sid] = new Map();
      const msgMap = bySession[sid];
      if (!msgMap.has(mid)) msgMap.set(mid, { ts: d?.timestamp ?? 0, parts: [] });
      msgMap.get(mid)!.parts.push(part);
    }
    // Convert to SessionMessage[]
    const result: Record<string, SessionMessage[]> = {};
    for (const [sid, msgMap] of Object.entries(bySession)) {
      const msgs: SessionMessage[] = Array.from(msgMap.values())
        .sort((a, b) => a.ts - b.ts)
        .map(({ parts }) => ({
          info: { role: 'assistant' as const },
          parts,
        }));
      if (msgs.length > 0) result[sid] = msgs;
    }
    return result;
  }, [entries]);

  // For any session ID not in the shared messagesBySession, try the API first
  useEffect(() => {
    for (const sid of sessionIds) {
      if (!messagesBySession[sid] && !fetchedRef.current.has(sid)) {
        fetchedRef.current.add(sid);
        (api.openCodeMessages(host, sid) as Promise<any>)
          .then((msgs: any) => {
            // Only store if API actually returned messages; otherwise timeline fallback is used
            if (Array.isArray(msgs) && msgs.length > 0) {
              setExtraMessages((prev) => ({ ...prev, [sid]: msgs }));
            }
          })
          .catch(() => {});
      }
    }
  }, [sessionIds, messagesBySession, host]);

  // Collect all OpenCode messages: shared stream > API fetch > timeline reconstruction
  const ocMessages = useMemo(() => {
    const msgs: SessionMessage[] = [];
    for (const sid of sessionIds) {
      const sm = messagesBySession[sid] ?? extraMessages[sid] ?? timelineMessages[sid];
      if (sm) msgs.push(...sm);
    }
    return msgs;
  }, [sessionIds, messagesBySession, extraMessages, timelineMessages]);

  const msgCount = ocMessages.length;

  // Default tab: show messages when we have them, otherwise timeline
  const [tab, setTab] = useState<'messages' | 'timeline'>('timeline');
  const switchedRef = useRef(false);
  useEffect(() => {
    if (msgCount > 0 && !switchedRef.current) {
      setTab('messages');
      switchedRef.current = true;
    }
  }, [msgCount]);

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

      <div className="mb-3 grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-white">{entries.length}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Events</p>
        </div>
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className="text-2xl font-bold text-purple-400">{msgCount}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Messages</p>
        </div>
        <div className="rounded-lg bg-black/30 p-3 text-center">
          <p className={`truncate text-sm font-bold ${lastEntry ? LEVEL_STYLES[lastEntry.level] ?? 'text-trident-muted' : 'text-trident-muted'}`}>
            {lastEntry?.level ?? '—'}
          </p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Last Level</p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="mb-2 flex gap-1 rounded-lg bg-black/20 p-1">
        <button
          onClick={() => setTab('messages')}
          className={`flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            tab === 'messages'
              ? 'bg-trident-accent/20 text-trident-accent'
              : 'text-trident-muted hover:text-white'
          }`}
        >
          <MessageSquare size={10} className="mr-1 inline" />
          Messages ({msgCount})
        </button>
        <button
          onClick={() => setTab('timeline')}
          className={`flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            tab === 'timeline'
              ? 'bg-trident-accent/20 text-trident-accent'
              : 'text-trident-muted hover:text-white'
          }`}
        >
          Timeline ({entries.length})
        </button>
      </div>

      {tab === 'messages' ? (
        msgCount === 0 ? (
          <p className="py-4 text-center text-sm text-trident-muted">
            {sessionIds.length === 0
              ? 'No OpenCode session linked yet'
              : 'Waiting for messages…'}
          </p>
        ) : (
          <div className="flex-1 overflow-auto max-h-80">
            <SessionStream messages={ocMessages} />
          </div>
        )
      ) : entries.length === 0 ? (
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

function HostPanel({ host, stream }: { host: string; stream: ReturnType<typeof useOpenCodeStream> }) {
  const { sessions, messagesBySession, connected } = stream;

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
  // Lift OpenCode streams — one per host, shared by all agent panels
  const compromisedStream = useOpenCodeStream('compromised');
  const serverStream = useOpenCodeStream('server');

  const streamByHost: Record<string, ReturnType<typeof useOpenCodeStream>> = {
    compromised: compromisedStream,
    server: serverStream,
  };

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
              host={a.host}
              messagesBySession={streamByHost[a.host]?.messagesBySession ?? {}}
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
            <HostPanel key={host} host={host} stream={streamByHost[host]} />
          ))}
        </div>
      </div>
    </div>
  );
}
