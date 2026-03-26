import { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { api } from '@/api';
import { useOpenCodeStream } from '@/hooks/useOpenCodeStream';
import { SessionStream } from '@/components/SessionStream';
import type { SessionMessage } from '@/types';

export function SessionDetailPage() {
  const { host = 'compromised', sessionId = '' } = useParams<{
    host: string;
    sessionId: string;
  }>();

  const { messagesBySession, sessions, connected } = useOpenCodeStream(host);
  const [restMessages, setRestMessages] = useState<SessionMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load initial messages via REST
  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    api
      .openCodeMessages(sessionId)
      .then((data: any) => {
        // Normalize: API may return raw messages or wrapped
        const msgs = Array.isArray(data) ? data : [];
        setRestMessages(msgs as SessionMessage[]);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [host, sessionId]);

  // Combine REST + WS messages (WS appends new ones)
  const wsMessages = messagesBySession[sessionId] || [];
  const allMessages = restMessages.length > 0 ? restMessages : wsMessages;

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [allMessages.length]);

  const rawStatus = sessions[sessionId] || 'unknown';
  const status = typeof rawStatus === 'string' ? rawStatus : (rawStatus as any)?.type ?? 'unknown';

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-4 flex items-center gap-4">
        <Link to="/agents" className="btn-ghost p-2">
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1">
          <h2 className="font-heading text-xl font-bold text-white">
            Session on <span className="capitalize text-trident-accent">{host}</span>
          </h2>
          <p className="font-mono text-xs text-trident-muted">{sessionId}</p>
        </div>
        <span
          className={`badge ${
            status === 'busy' || status === 'running'
              ? 'badge-warning'
              : status === 'idle'
              ? 'badge-success'
              : 'badge-muted'
          }`}
        >
          {status}
        </span>
        <span className={`badge ${connected ? 'badge-success' : 'badge-danger'}`}>
          {connected ? 'Live' : 'Offline'}
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto rounded-xl border border-trident-border bg-trident-surface/30 p-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw size={20} className="animate-spin text-trident-accent" />
          </div>
        ) : (
          <>
            <SessionStream messages={allMessages} sessionId={sessionId} />
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  );
}
