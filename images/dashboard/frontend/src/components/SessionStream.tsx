import type { MessagePart, SessionMessage } from '@/types';
import { ChevronDown, ChevronRight, Terminal, MessageSquare, Wrench, Maximize2, X } from 'lucide-react';
import { useState, useEffect } from 'react';

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
          <MessageSquare size={14} className="mt-0.5 flex-shrink-0 text-blue-700 dark:text-blue-400" />
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
        <div className="my-1 rounded-lg border border-trident-border bg-black/5 dark:bg-black/30">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-black/5 dark:hover:bg-white/5"
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <Wrench size={12} className="text-amber-700 dark:text-amber-400 flex-shrink-0" />
            <span className="font-mono font-medium text-amber-700 dark:text-amber-400 flex-shrink-0">{toolName}</span>
            {summary && (
              <span className="truncate text-trident-muted font-mono">{summary}</span>
            )}
          </button>
          {expanded && (
            <div className="space-y-2 border-t border-trident-border px-3 py-2">
              {typeof input === 'object' && Object.keys(input).length > 0 && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-trident-muted">Input</span>
                  <pre className="terminal-output mt-1 max-h-60 overflow-auto text-yellow-400 dark:text-yellow-300">
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

/** Fullscreen modal for viewing a single message */
function MessageFullscreenModal({ message, onClose }: { message: SessionMessage; onClose: () => void }) {
  // Handle Escape key to close
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="relative h-full w-full max-w-5xl overflow-auto p-8"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button - larger, always visible */}
        <button
          onClick={onClose}
          className="fixed top-6 right-6 z-50 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-600 border-2 border-red-400 text-white shadow-2xl backdrop-blur-sm transition-all hover:bg-red-700 hover:scale-105 active:scale-95 dark:bg-red-500/90 dark:border-white/20"
          aria-label="Close fullscreen"
        >
          <X size={32} strokeWidth={3} />
        </button>

        {/* Message content */}
        <div className="rounded-xl border border-trident-border bg-white dark:bg-black/60 backdrop-blur-xl p-8 shadow-2xl ring-1 ring-trident-border dark:ring-white/5">
          {/* Message header */}
          <div className="mb-6 flex items-center gap-4 border-b border-trident-border dark:border-white/10 pb-5">
            <span className={`badge ${message.info?.role === 'assistant' ? 'badge-info' : 'badge-muted'} text-sm px-4 py-1.5`}>
              {message.info?.role || 'unknown'}
            </span>
            {message.info?.tokens && (
              <span className="text-sm text-trident-muted">
                {message.info.tokens.input}↓ {message.info.tokens.output}↑ tokens
              </span>
            )}
            {message.info?.time?.created && (
              <span className="ml-auto text-sm text-trident-muted">
                {new Date(message.info.time.created).toLocaleString()}
              </span>
            )}
          </div>

          {/* Message parts */}
          <div className="space-y-6">
            {(Array.isArray(message.parts) ? message.parts : []).map((part, pIdx) => {
              // Cast to access tool-specific properties
              const toolPart = part as any;
              return (
                <div key={pIdx}>
                  {part.type === 'text' ? (
                    <div>
                      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-trident-muted">
                        <MessageSquare size={16} className="text-blue-700 dark:text-blue-400" />
                        Text
                      </div>
                      <pre className="whitespace-pre-wrap break-words text-base text-trident-text font-mono leading-relaxed">
                        {typeof part.text === 'string' ? part.text : JSON.stringify(part.text)}
                      </pre>
                    </div>
                  ) : part.type === 'tool' ? (
                    <div className="rounded-xl border border-trident-border dark:border-white/10 bg-gray-100 dark:bg-black/40">
                      <div className="flex items-center gap-3 px-5 py-4 border-b border-trident-border dark:border-white/10">
                        <Wrench size={16} className="text-amber-700 dark:text-amber-500 flex-shrink-0" />
                        <span className="font-mono font-semibold text-amber-700 dark:text-amber-500 text-sm">
                          {part.tool || 'unknown_tool'}
                        </span>
                      </div>
                      <div className="space-y-5 p-5">
                        {toolPart.state && (
                          <>
                            {typeof toolPart.state.input === 'object' && Object.keys(toolPart.state.input).length > 0 && (
                              <div>
                                <span className="text-xs uppercase tracking-wider text-trident-muted mb-3 block">Input</span>
                                <pre className="terminal-output text-base text-yellow-700 dark:text-yellow-300 rounded-lg bg-gray-200 dark:bg-black/30 p-4">
                                  {JSON.stringify(toolPart.state.input, null, 2)}
                                </pre>
                              </div>
                            )}
                            {toolPart.state.output && (
                              <div>
                                <span className="text-xs uppercase tracking-wider text-trident-muted mb-3 block">Output</span>
                                <pre className="terminal-output text-base rounded-lg bg-gray-200 dark:bg-black/30 p-4">
                                  {typeof toolPart.state.output === 'string' ? toolPart.state.output : JSON.stringify(toolPart.state.output, null, 2)}
                                </pre>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function SessionStream({ messages, sessionId }: Props) {
  const [maximizedMessage, setMaximizedMessage] = useState<SessionMessage | null>(null);

  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-trident-muted">
        <Terminal size={16} className="mr-2" />
        Waiting for messages…
      </div>
    );
  }

  return (
    <>
      <div className="space-y-2">
        {messages.map((msg, idx) => (
          <div key={idx} className="group relative rounded-lg border border-trident-border bg-trident-surface/50 p-3">
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

            {/* Maximize button - appears on hover */}
            <button
              onClick={() => setMaximizedMessage(msg)}
              className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded bg-trident-surface border border-trident-border text-trident-muted opacity-0 transition-all hover:border-trident-accent hover:text-trident-accent group-hover:opacity-100"
              aria-label="Maximize message"
              title="Maximize message"
            >
              <Maximize2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Fullscreen modal */}
      {maximizedMessage && (
        <MessageFullscreenModal
          message={maximizedMessage}
          onClose={() => setMaximizedMessage(null)}
        />
      )}
    </>
  );
}
