import type { MessagePart, SessionMessage } from '@/types';
import { ChevronDown, ChevronRight, Terminal, MessageSquare, Wrench } from 'lucide-react';
import { useState } from 'react';

const TEXT_PREVIEW_LENGTH = 300;

/** Extract a one-line human-readable description from a tool's input object. */
function toolInputSummary(input: unknown): string {
  if (typeof input === 'string') return input.trim().replace(/\n/g, ' ').slice(0, 120);
  if (!input || typeof input !== 'object') return '';
  const obj = input as Record<string, unknown>;
  // Prefer human-readable description fields first, then raw command/content
  const priorityKeys = ['description', 'title', 'command', 'cmd', 'query', 'message', 'content', 'path', 'url', 'file', 'filename', 'text', 'code', 'script', 'input'];
  for (const key of priorityKeys) {
    const val = obj[key];
    if (typeof val === 'string' && val.trim()) {
      return val.trim().replace(/\n/g, ' ').slice(0, 120);
    }
  }
  // Fallback: first string value
  for (const val of Object.values(obj)) {
    if (typeof val === 'string' && val.trim()) {
      return val.trim().replace(/\n/g, ' ').slice(0, 120);
    }
  }
  return '';
}

function PartRenderer({ part }: { part: MessagePart }) {
  const [expanded, setExpanded] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);

  switch (part.type) {
    case 'text': {
      const raw = typeof part.text === 'string' ? part.text : JSON.stringify(part.text);
      const isLong = raw.length > TEXT_PREVIEW_LENGTH;
      const displayed = isLong && !textExpanded ? raw.slice(0, TEXT_PREVIEW_LENGTH) + '…' : raw;
      return (
        <div className="flex gap-2 py-1">
          <MessageSquare size={14} className="mt-0.5 flex-shrink-0 text-blue-400" />
          <div className="min-w-0 flex-1">
            <pre className="whitespace-pre-wrap break-words text-xs text-trident-text font-mono leading-relaxed">
              {displayed}
            </pre>
            {isLong && (
              <button
                onClick={() => setTextExpanded((v) => !v)}
                className="mt-0.5 text-[10px] text-trident-accent hover:underline"
              >
                {textExpanded ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>
        </div>
      );
    }

    case 'tool': {
      const toolName = part.tool || 'unknown_tool';
      const state = (part as any).state ?? {};
      const input = state.input ?? (part as any).input ?? (part as any).args ?? {};
      const output = state.output ?? (part as any).output ?? (part as any).result ?? '';
      const summary = toolInputSummary(input);
      return (
        <div className="my-1 rounded-lg border border-trident-border bg-black/30">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-white/5"
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Wrench size={12} className="text-amber-400 flex-shrink-0" />
            <span className="font-mono font-medium text-amber-400 flex-shrink-0">{toolName}</span>
            {summary && (
              <span className="truncate text-trident-muted font-mono">{summary}</span>
            )}
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
    case 'step-finish':
    case 'step_finish':
      return null;

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
