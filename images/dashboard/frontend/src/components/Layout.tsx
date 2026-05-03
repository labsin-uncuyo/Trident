import { NavLink, Outlet } from 'react-router-dom';
import {
  Network,
  Bot,
  ShieldAlert,
  Wifi,
  FolderOpen,
  Activity,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  X,
} from 'lucide-react';
import { ContainerStatusBar } from './ContainerStatusBar';
import { ReplayProvider, useReplayContext } from '@/contexts/ReplayContext';
import { useState } from 'react';

const navItems = [
  { to: '/', icon: Network, label: 'Topology' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/alerts', icon: ShieldAlert, label: 'Alerts' },
  { to: '/traffic', icon: Wifi, label: 'Traffic' },
  { to: '/runs', icon: FolderOpen, label: 'Runs' },
];

// Replay Control Bar component
function ReplayControlBar() {
  const { replay, controls, isLoading, error } = useReplayContext();
  const [showRunSelector, setShowRunSelector] = useState(false);
  const [runs, setRuns] = useState<Array<{ run_id: string; path: string; is_current: boolean }>>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  const formatTime = (ms: number): string => {
    if (ms < 0) ms = 0;
    // If this looks like an absolute timestamp (very large number), convert to offset from start
    let displayMs = ms;
    if (replay.startTimeMs > 0 && ms > 1000000000000) {  // Absolute timestamp detected
      displayMs = ms - replay.startTimeMs;
    }
    const totalSeconds = Math.floor(displayMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  const fetchRuns = async () => {
    setLoadingRuns(true);
    try {
      const res = await fetch('/api/replay/runs');
      const data = await res.json();
      setRuns(data.runs || []);
    } catch (e) {
      console.error('Failed to fetch runs', e);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleLoadRun = (path: string, runId: string) => {
    controls.loadReplay(path, runId);
    setShowRunSelector(false);
  };

  const handleStop = () => {
    controls.stop();
  };

  // Don't show if no replay is loaded
  if (!replay.replayId && !isLoading) {
    return (
      <div className="border-t border-trident-border bg-trident-surface px-4 py-2">
        <button
          onClick={() => {
            setShowRunSelector(!showRunSelector);
            if (!showRunSelector && runs.length === 0) fetchRuns();
          }}
          className="flex items-center gap-2 text-sm text-trident-muted hover:text-white transition-colors"
        >
          <Play size={14} />
          Load Replay
        </button>

        {showRunSelector && (
          <div className="mt-3 border border-trident-border rounded-lg bg-black/30 p-2 max-h-48 overflow-auto">
            {loadingRuns ? (
              <div className="text-xs text-trident-muted py-2">Loading runs...</div>
            ) : runs.length === 0 ? (
              <div className="text-xs text-trident-muted py-2">No runs found</div>
            ) : (
              runs.map((run) => (
                <button
                  key={run.run_id}
                  onClick={() => handleLoadRun(run.path, run.run_id)}
                  className="w-full text-left px-2 py-1 text-xs text-trident-text hover:bg-white/10 rounded flex items-center justify-between"
                >
                  <span className="font-mono truncate">{run.run_id}</span>
                  {run.is_current && <span className="text-[10px] text-trident-accent">current</span>}
                </button>
              ))
            )}
          </div>
        )}
      </div>
    );
  }

  const progress = replay.durationMs > 0 ? (replay.positionMs / replay.durationMs) * 100 : 0;

  return (
    <div className="border-t border-trident-border bg-trident-surface px-4 py-2">
      <div className="flex items-center gap-3">
        {/* Stop button */}
        <button
          onClick={handleStop}
          className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-white hover:bg-white/10 transition-colors"
          title="Stop replay"
        >
          <X size={14} />
        </button>

        {/* Replay name */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-mono text-white truncate">{replay.replayId}</div>
          <div className="flex items-center gap-2 mt-1">
            {/* Play/Pause */}
            <button
              onClick={controls.togglePlay}
              className="flex h-7 w-7 items-center justify-center rounded bg-trident-accent text-white hover:bg-trident-accent/80 transition-colors"
              title={replay.isPlaying ? 'Pause' : 'Play'}
            >
              {replay.isPlaying ? <Pause size={12} /> : <Play size={12} />}
            </button>

            {/* Skip buttons */}
            <button
              onClick={() => controls.seek(Math.max(0, replay.positionMs - 10000))}
              className="flex h-6 w-6 items-center justify-center rounded text-trident-muted hover:text-white hover:bg-white/10 transition-colors"
              title="Back 10s"
            >
              <SkipBack size={12} />
            </button>
            <button
              onClick={() => controls.seek(Math.min(replay.durationMs, replay.positionMs + 10000))}
              className="flex h-6 w-6 items-center justify-center rounded text-trident-muted hover:text-white hover:bg-white/10 transition-colors"
              title="Forward 10s"
            >
              <SkipForward size={12} />
            </button>

            {/* Timeline slider */}
            <div className="flex-1">
              <input
                type="range"
                min={0}
                max={replay.durationMs}
                value={replay.positionMs}
                onChange={(e) => controls.seek(Number(e.target.value))}
                className="w-full h-1.5 bg-trident-border rounded-lg appearance-none cursor-pointer accent-trident-accent"
                style={{
                  background: `linear-gradient(to right, var(--trident-accent) ${progress}%, var(--trident-border) ${progress}%)`,
                }}
              />
            </div>

            {/* Speed selector */}
            <select
              value={replay.speed}
              onChange={(e) => {
                const newSpeed = Number(e.target.value);
                controls.setSpeed(newSpeed);
                if (replay.isPlaying) controls.play(newSpeed);
              }}
              className="px-1 py-0.5 text-xs bg-trident-bg border border-trident-border rounded text-trident-text focus:outline-none"
            >
              <option value={0.5}>0.5x</option>
              <option value={1}>1x</option>
              <option value={2}>2x</option>
              <option value={5}>5x</option>
              <option value={10}>10x</option>
              <option value={25}>25x</option>
              <option value={50}>50x</option>
              <option value={100}>100x</option>
            </select>

            {/* Time display */}
            <span className="text-xs font-mono text-trident-muted min-w-[70px] text-right">
              {formatTime(replay.positionMs)} / {formatTime(replay.durationMs)}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-2 text-xs text-red-400">{error}</div>
      )}
    </div>
  );
}

function LayoutContent() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col border-r border-trident-border bg-trident-surface">
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-trident-border px-5 py-4">
          <img src="/trident.svg" alt="Trident" className="h-8 w-8" />
          <div>
            <h1 className="font-heading text-lg font-bold tracking-tight text-white">
              TRIDENT
            </h1>
            <p className="text-[10px] uppercase tracking-widest text-trident-muted">
              Dashboard
            </p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `nav-link ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Status bar at bottom */}
        <ContainerStatusBar />
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden bg-trident-bg">
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>

        {/* Replay Control Bar */}
        <ReplayControlBar />
      </main>
    </div>
  );
}

export function Layout() {
  return (
    <ReplayProvider>
      <LayoutContent />
    </ReplayProvider>
  );
}
