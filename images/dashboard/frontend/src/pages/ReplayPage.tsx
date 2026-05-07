import { useState, useMemo, useEffect, useRef } from 'react';
import { Play, FolderOpen, RefreshCw, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import { useReplayRuns } from '@/hooks/useReplay';
import { TimelineControls } from '@/components/TimelineControls';
import { SessionStream } from '@/components/SessionStream';
import { useReplayContext } from '@/contexts/ReplayContext';
import type { ReplayEvent, SessionMessage } from '@/types';

// Convert replay events to SessionMessage format for SessionStream component
function replayEventsToSessionMessages(events: ReplayEvent[]): SessionMessage[] {
  const messagesBySession: Record<string, SessionMessage[]> = {};

  for (const event of events) {
    // Only process opencode events that have parts
    if (event.source_type === 'opencode' && event.parts && Array.isArray(event.parts)) {
      const sessionId = event.session_id || event.info?.sessionID || 'default';
      if (!messagesBySession[sessionId]) {
        messagesBySession[sessionId] = [];
      }
      messagesBySession[sessionId].push({
        info: event.info,
        parts: event.parts,
      });
    }
  }

  // Flatten all messages into a single array
  const allMessages: SessionMessage[] = [];
  for (const messages of Object.values(messagesBySession)) {
    allMessages.push(...messages);
  }

  // Sort by timestamp
  allMessages.sort((a, b) => {
    const aTime = a.info?.time?.created || (a.info as any)?.timestamp || 0;
    const bTime = b.info?.time?.created || (b.info as any)?.timestamp || 0;
    return aTime - bTime;
  });

  return allMessages;
}

// Timeline entry row component (similar to AgentsPage)
function TimelineEntryRow({ entry }: { entry: ReplayEvent }) {
  const [expanded, setExpanded] = useState(false);

  const LEVEL_STYLES: Record<string, string> = {
    INIT: 'text-blue-700 dark:text-blue-400',
    OPENCODE: 'text-purple-700 dark:text-purple-400',
    ERROR: 'text-red-700 dark:text-red-400',
    WARNING: 'text-amber-700 dark:text-amber-400',
    INFO: 'text-green-700 dark:text-green-400',
    DEBUG: 'text-trident-muted',
    ALERT: 'text-red-700 dark:text-red-500',
  };

  const levelColor = LEVEL_STYLES[entry.level || ''] ?? 'text-trident-muted';
  const levelLabel = entry.level || (entry.source_type === 'alert' ? 'ALERT' : entry.source_type);

  // Format time
  const timeStr = entry.ts
    ? entry.ts.slice(11, 19)
    : new Date(entry.timestamp_ms).toISOString().slice(11, 19);

  // Get display message
  let displayMsg = entry.msg || '';
  if (!displayMsg && entry.data) {
    const d = entry.data as Record<string, unknown>;
    const type = d.type as string;
    if (type === 'text' && d.part) {
      const part = d.part as Record<string, unknown>;
      const text = part.text as string;
      if (text) displayMsg = text.replace(/\n/g, ' ').slice(0, 120);
    } else if (type === 'tool_use' && d.part) {
      const part = d.part as Record<string, unknown>;
      const tool = part.tool as string;
      const state = part.state as Record<string, unknown>;
      const input = state?.input as Record<string, unknown>;
      const desc = (input?.description ?? input?.command ?? input?.query ?? input?.content ?? '') as string;
      displayMsg = `${tool}${desc ? ` · ${desc.replace(/\n/g, ' ').slice(0, 100)}` : ''}`;
    }
  }

  // Hide step_start/step_finish entries
  if (entry.level === 'OPENCODE') {
    const d = entry.data as Record<string, unknown> | undefined;
    const type = d?.type as string;
    if (type === 'step_start' || type === 'step-start' || type === 'step_finish' || type === 'step-finish') {
      return null;
    }
  }

  return (
    <div
      className="cursor-pointer border-b border-trident-border/40 px-3 py-1.5 hover:bg-black/5 dark:hover:bg-white/5"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-start gap-2 text-xs">
        <span className="w-16 flex-shrink-0 font-mono text-[10px] text-trident-muted">
          {timeStr}
        </span>
        <span className={`w-24 flex-shrink-0 font-mono font-bold ${levelColor}`}>
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

// Run selector card
function RunSelector({
  runs,
  loading,
  error,
  onSelect,
  currentPath,
}: {
  runs: Array<{ run_id: string; path: string; is_current: boolean; created: string }>;
  loading: boolean;
  error: string | null;
  onSelect: (path: string, runId: string) => void;
  currentPath: string | null;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="card">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between p-4 text-left"
      >
        <div className="flex items-center gap-2">
          <FolderOpen size={18} className="text-trident-accent" />
          <h3 className="font-heading text-lg font-bold text-trident-text">Select Run to Replay</h3>
        </div>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <RefreshCw size={20} className="animate-spin text-trident-accent" />
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-700 dark:text-red-400 py-4">
              <AlertCircle size={16} />
              <span className="text-sm">{error}</span>
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-trident-muted py-4">No runs found in /outputs</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-auto">
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  onClick={() => onSelect(run.path, run.run_id)}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border transition-colors text-left ${
                    currentPath === run.path
                      ? 'border-trident-accent bg-trident-accent/20'
                      : 'border-trident-border hover:border-trident-accent/50 hover:bg-trident-accent/5'
                  }`}
                >
                  <div>
                    <div className="font-mono text-sm text-trident-text">
                      {run.run_id}
                      {run.is_current && (
                        <span className="ml-2 text-xs text-trident-accent">(current)</span>
                      )}
                    </div>
                    <div className="text-xs text-trident-muted mt-1">
                      {new Date(run.created).toLocaleString()}
                    </div>
                  </div>
                  <Play size={14} className="text-trident-muted" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Tab switcher
function TabSwitcher<T extends string>({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: Array<{ key: T; label: string; count: number }>;
  activeTab: T;
  onTabChange: (tab: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-lg bg-black/5 dark:bg-black/20 p-1 mb-4">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
            activeTab === tab.key
              ? 'bg-trident-accent/20 text-trident-accent'
              : 'text-trident-muted hover:text-trident-text'
          }`}
        >
          {tab.label} ({tab.count})
        </button>
      ))}
    </div>
  );
}

export function ReplayPage() {
  // State for selected run
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [viewTab, setViewTab] = useState<'timeline' | 'messages'>('timeline');

  // Custom path input
  const [customPath, setCustomPath] = useState('');

  // Use the global ReplayContext instead of local useReplay hook
  const { replay, controls, isLoading, error } = useReplayContext();

  // Available runs
  const { runs, loading: runsLoading, error: runsError } = useReplayRuns();

  // Auto-select current run if available
  useEffect(() => {
    const currentRun = runs.find((r) => r.is_current);
    if (currentRun && !selectedRunId && !error) {
      // Don't auto-select, let user choose
    }
  }, [runs]);

  // Reset to timeline view when a new replay is loaded
  useEffect(() => {
    if (replay.replayId) {
      setViewTab('timeline');
    }
  }, [replay.replayId]);

  // Convert events to session messages
  const sessionMessages = useMemo(() => {
    return replayEventsToSessionMessages(replay.events);
  }, [replay.events]);

  // Timeline entries (all events)
  const timelineEntries = replay.events;

  // Event counts by type
  const eventCounts = useMemo(() => {
    const counts = { timeline: 0, messages: 0, alerts: 0 };
    for (const e of replay.events) {
      counts.timeline++;
      if (e.source_type === 'opencode') counts.messages++;
      if (e.source_type === 'alert') counts.alerts++;
    }
    return counts;
  }, [replay.events]);

  // Handle run selection
  const handleSelectRun = async (path: string, runId: string) => {
    setSelectedPath(path);
    setSelectedRunId(runId);
    await controls.loadReplay(path, runId);
  };

  // Handle custom path load
  const handleLoadCustomPath = async () => {
    if (customPath.trim()) {
      setSelectedPath(customPath.trim());
      setSelectedRunId(null);
      await controls.loadReplay(customPath.trim());
    }
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto">
      {/* Header */}
      <div>
        <h2 className="font-heading text-2xl font-bold text-trident-text">Replay</h2>
        <p className="text-sm text-trident-muted">
          Replay historical logs with timeline and playback controls
        </p>
      </div>

      {/* Run Selector */}
      <RunSelector
        runs={runs}
        loading={runsLoading}
        error={runsError}
        onSelect={handleSelectRun}
        currentPath={selectedPath}
      />

      {/* Custom Path Input */}
      <div className="card">
        <div className="flex items-center gap-2 mb-2">
          <FolderOpen size={16} className="text-trident-accent" />
          <h3 className="font-heading text-sm font-bold text-trident-text">Or enter custom path:</h3>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={customPath}
            onChange={(e) => setCustomPath(e.target.value)}
            placeholder="/outputs/run_20250102_123456"
            className="flex-1 px-3 py-2 rounded bg-trident-bg border border-trident-border text-sm text-trident-text focus:outline-none focus:border-trident-accent font-mono"
            onKeyDown={(e) => e.key === 'Enter' && handleLoadCustomPath()}
          />
          <button
            onClick={handleLoadCustomPath}
            className="px-4 py-2 bg-trident-accent rounded text-sm font-medium hover:bg-trident-accent/80 transition-colors"
          >
            Load
          </button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="card bg-red-500/10 border-red-500/50">
          <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
            <AlertCircle size={16} />
            <span className="text-sm">{error}</span>
          </div>
        </div>
      )}

      {/* Replay Controls */}
      {replay.replayId && replay.durationMs > 0 && (
        <>
          <TimelineControls
            duration={replay.durationMs}
            position={replay.positionMs - replay.startTimeMs}  // Convert to offset
            startTimeMs={replay.startTimeMs}
            isPlaying={replay.isPlaying}
            speed={replay.speed}
            onPlay={controls.play}
            onPause={controls.pause}
            onSeek={(offset) => controls.seek(offset + replay.startTimeMs)}  // Convert back to absolute
            onSpeedChange={controls.setSpeed}
          />

          {/* Stats */}
          <div className="grid grid-cols-4 gap-3">
            <div className="rounded-lg bg-black/5 dark:bg-black/30 p-3 text-center">
              <p className="text-2xl font-bold text-trident-text">{replay.eventCount}</p>
              <p className="text-[10px] uppercase tracking-wider text-trident-muted">Total Events</p>
            </div>
            <div className="rounded-lg bg-black/5 dark:bg-black/30 p-3 text-center">
              <p className="text-2xl font-bold text-purple-700 dark:text-purple-400">{eventCounts.messages}</p>
              <p className="text-[10px] uppercase tracking-wider text-trident-muted">Messages</p>
            </div>
            <div className="rounded-lg bg-black/5 dark:bg-black/30 p-3 text-center">
              <p className="text-2xl font-bold text-blue-700 dark:text-blue-400">{eventCounts.timeline}</p>
              <p className="text-[10px] uppercase tracking-wider text-trident-muted">Timeline</p>
            </div>
            <div className="rounded-lg bg-black/5 dark:bg-black/30 p-3 text-center">
              <p className="text-2xl font-bold text-red-700 dark:text-red-400">{eventCounts.alerts}</p>
              <p className="text-[10px] uppercase tracking-wider text-trident-muted">Alerts</p>
            </div>
          </div>

          {/* Tab Switcher */}
          <TabSwitcher
            tabs={[
              { key: 'timeline', label: 'Timeline', count: eventCounts.timeline },
              { key: 'messages', label: 'Messages', count: eventCounts.messages },
            ]}
            activeTab={viewTab}
            onTabChange={setViewTab}
          />

          {/* Content Area */}
          <div className="flex-1 overflow-auto rounded-xl border border-trident-border bg-trident-surface/30 p-4">
            {viewTab === 'messages' ? (
              sessionMessages.length === 0 ? (
                <p className="py-8 text-center text-sm text-trident-muted">No messages to display</p>
              ) : (
                <SessionStream messages={sessionMessages} />
              )
            ) : timelineEntries.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                {replay.eventCount === 0 ? (
                  <>
                    <Play size={32} className="text-trident-muted mb-4" />
                    <p className="text-sm text-trident-muted">
                      {replay.isPlaying ? 'Replaying...' : 'Press play to start replay'}
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-trident-muted">No timeline events to display</p>
                )}
              </div>
            ) : (
              <div className="max-h-[500px] overflow-auto">
                {timelineEntries.map((event, idx) => (
                  <TimelineEntryRow key={`${event.timestamp_ms}_${idx}`} entry={event} />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Empty State */}
      {!replay.replayId && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FolderOpen size={48} className="text-trident-muted mb-4" />
          <h3 className="text-lg font-bold text-trident-text mb-2">No Replay Loaded</h3>
          <p className="text-sm text-trident-muted max-w-md">
            Select a run from the list above or enter a custom path to load and replay historical logs.
          </p>
        </div>
      )}
    </div>
  );
}
