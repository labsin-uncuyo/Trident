import type { MessagePart, SessionMessage } from '@/types';
import { ChevronDown, ChevronRight, Terminal, MessageSquare, Wrench, Play, CheckCircle } from 'lucide-react';
import { useState } from 'react';

function PartRenderer({ part }: { part: MessagePart }) {
  const [expanded, setExpanded] = useState(false);

  switch (part.type) {
    case 'text':
      return (
        <div className="flex gap-2 py-1">
          <MessageSquare size={14} className="mt-0.5 flex-shrink-0 text-blue-400" />
          <pre className="whitespace-pre-wrap break-words text-xs text-trident-text font-mono leading-relaxed">
            {typeof part.text === 'string' ? part.text : JSON.stringify(part.text)}
          </pre>
        </div>
      );

    case 'tool': {
      const toolName = part.tool || 'unknown_tool';
      const input = (part as any).input ?? (part as any).args ?? {};
      const output = (part as any).output ?? (part as any).result ?? '';
      return (
        <div className="my-1 rounded-lg border border-trident-border bg-black/30">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-white/5"
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Wrench size={12} className="text-amber-400" />
            <span className="font-mono font-medium text-amber-400">{toolName}</span>
          </button>
          {expanded && (
            <div className="space-y-2 border-t border-trident-border px-3 py-2">
              {typeof input === 'object' && Object.keys(input).length > 0 && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-trident-muted">Input</span>
                  <pre className="terminal-output mt-1 max-h-60 overflow-auto text-yellow-300">
                    {JSON.stringify(input, null, 2)}
                  </pre>
                </div>
              )}
              {output && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-trident-muted">Output</span>
                  <pre className="terminal-output mt-1 max-h-60 overflow-auto">
                    {typeof output === 'string' ? output : JSON.stringify(output, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      );
    }

    case 'step-start':
    case 'step_start':
      return (
        <div className="flex items-center gap-2 py-1 text-xs text-trident-muted">
          <Play size={10} className="text-green-400" />
          <span>Step started</span>
        </div>
      );

    case 'step-finish':
    case 'step_finish':
      return (
        <div className="flex items-center gap-2 py-1 text-xs text-trident-muted">
          <CheckCircle size={10} className="text-green-400" />
          <span>Step finished</span>
        </div>
      );

    default:
      return (
        <div className="py-1 text-xs text-trident-muted">
          <span className="font-mono">[{typeof part.type === 'string' ? part.type : 'unknown'}]</span>{' '}
          {typeof part.text === 'string' ? part.text : JSON.stringify(part).slice(0, 200)}
        </div>
      );
  }
}

interface Props {
  messages: SessionMessage[];
  sessionId?: string;
}

export function SessionStream({ messages, sessionId }: Props) {
  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-trident-muted">
        <Terminal size={16} className="mr-2" />
        Waiting for messages…
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {messages.map((msg, idx) => (
        <div key={idx} className="rounded-lg border border-trident-border bg-trident-surface/50 p-3">
          <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wider text-trident-muted">
            <span className={`badge ${msg.info?.role === 'assistant' ? 'badge-info' : 'badge-muted'}`}>
              {msg.info?.role || 'unknown'}
            </span>
            {msg.info?.tokens && (
              <span>
                {msg.info.tokens.input}↓ {msg.info.tokens.output}↑ tokens
              </span>
            )}
            {msg.info?.time?.created && (
              <span className="ml-auto">
                {new Date(msg.info.time.created).toLocaleTimeString()}
              </span>
            )}
          </div>
          <div className="space-y-1">
            {(Array.isArray(msg.parts) ? msg.parts : []).map((part, pIdx) => (
              <PartRenderer key={pIdx} part={part} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
