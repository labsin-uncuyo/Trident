import { NavLink, Outlet, useLocation } from 'react-router-dom';
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
  Sun,
  Moon,
} from 'lucide-react';
import { ContainerStatusBar } from './ContainerStatusBar';
import { ReplayProvider, useReplayContext } from '@/contexts/ReplayContext';
import { useState, useCallback, useEffect } from 'react';

const navItems = [
  { to: '/', icon: Network, label: 'Topology' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/alerts', icon: ShieldAlert, label: 'Alerts' },
  { to: '/traffic', icon: Wifi, label: 'Traffic' },
  { to: '/runs', icon: FolderOpen, label: 'Runs' },
  { to: '/replay', icon: Play, label: 'Replay' },
];

// Replay Control Bar component
function ReplayControlBar() {
  const { replay, controls, isLoading, error } = useReplayContext();
  const [showRunSelector, setShowRunSelector] = useState(false);
  const [runs, setRuns] = useState<Array<{ run_id: string; path: string; is_current: boolean }>>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [timeInput, setTimeInput] = useState('');
  const [inputError, setInputError] = useState(false);
  const [isUserEditing, setIsUserEditing] = useState(false);

  const formatTime = useCallback((ms: number): string => {
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
  }, [replay.startTimeMs]);

  // Update the time input when position changes
  useEffect(() => {
    if (!isUserEditing) {
      setTimeInput(formatTime(replay.positionMs));
    }
  }, [replay.positionMs, isUserEditing, formatTime]);

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

  // Parse time string in formats: "MM:SS", "HH:MM:SS", or "SS" (seconds only)
  // Returns an absolute timestamp (startTimeMs + offset)
  const parseTimeToMs = useCallback((timeStr: string): number | null => {
    if (!timeStr.trim()) return null;

    // Parse as offset from start
    let offsetMs = 0;

    // Try just seconds first (plain number)
    const secondsOnly = parseFloat(timeStr);
    if (!isNaN(secondsOnly)) {
      offsetMs = secondsOnly * 1000;
    } else {
      // Try HH:MM:SS or MM:SS format
      const parts = timeStr.split(':').map(p => parseInt(p, 10));

      if (parts.length === 2 && parts.every(p => !isNaN(p))) {
        // MM:SS format
        const [mins, secs] = parts;
        offsetMs = (mins * 60 + secs) * 1000;
      } else if (parts.length === 3 && parts.every(p => !isNaN(p))) {
        // HH:MM:SS format
        const [hrs, mins, secs] = parts;
        offsetMs = (hrs * 3600 + mins * 60 + secs) * 1000;
      } else {
        return null;
      }
    }

    // Convert offset to absolute timestamp
    const absoluteMs = replay.startTimeMs + offsetMs;

    // Clamp to valid range
    return Math.min(replay.startTimeMs + replay.durationMs, Math.max(replay.startTimeMs, absoluteMs));
  }, [replay.startTimeMs, replay.durationMs]);

  const handleTimeInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setIsUserEditing(true);
    setTimeInput(e.target.value);
    setInputError(false);
  };

  const handleTimeInputSubmit = () => {
    const ms = parseTimeToMs(timeInput);
    if (ms !== null) {
      controls.seek(ms);
      controls.play(replay.speed); // Auto-play when seeking via text input
      setInputError(false);
      setIsUserEditing(false);
    } else {
      setInputError(true);
    }
  };

  const handleTimeInputBlur = () => {
    // Reset to current position on blur if user didn't submit
    setIsUserEditing(false);
    setInputError(false);
    setTimeInput(formatTime(replay.positionMs));
  };

  const handleTimeInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleTimeInputSubmit();
    } else if (e.key === 'Escape') {
      // Cancel editing on Escape
      setIsUserEditing(false);
      setInputError(false);
      setTimeInput(formatTime(replay.positionMs));
    }
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
          className="flex items-center gap-2 text-sm text-trident-muted hover:text-trident-text transition-colors"
        >
          <Play size={14} />
          Load Replay
        </button>

        {showRunSelector && (
          <div className="mt-3 border border-trident-border rounded-lg bg-black/30 dark:bg-black/30 p-2 max-h-48 overflow-auto">
            {loadingRuns ? (
              <div className="text-xs text-trident-muted py-2">Loading runs...</div>
            ) : runs.length === 0 ? (
              <div className="text-xs text-trident-muted py-2">No runs found</div>
            ) : (
              runs.map((run) => (
                <button
                  key={run.run_id}
                  onClick={() => handleLoadRun(run.path, run.run_id)}
                  className="w-full text-left px-2 py-1 text-xs text-trident-text hover:bg-black/10 dark:hover:bg-white/10 rounded flex items-center justify-between"
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
          className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-trident-text hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
          title="Stop replay"
        >
          <X size={14} />
        </button>

        {/* Replay name */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-mono text-trident-text truncate">{replay.replayId}</div>
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
              className="flex h-6 w-6 items-center justify-center rounded text-trident-muted hover:text-trident-text hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
              title="Back 10s"
            >
              <SkipBack size={12} />
            </button>
            <button
              onClick={() => controls.seek(Math.min(replay.durationMs, replay.positionMs + 10000))}
              className="flex h-6 w-6 items-center justify-center rounded text-trident-muted hover:text-trident-text hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
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

            {/* Time input */}
            <div className="relative">
              <input
                type="text"
                value={timeInput}
                onChange={handleTimeInputChange}
                onKeyDown={handleTimeInputKeyDown}
                onBlur={handleTimeInputBlur}
                placeholder="MM:SS"
                className={`w-20 px-2 py-0.5 text-xs font-mono bg-trident-bg border rounded text-trident-text focus:outline-none ${
                  inputError
                    ? 'border-red-500 focus:border-red-500'
                    : 'border-trident-border focus:border-trident-accent'
                }`}
                title="Enter time as MM:SS, HH:MM:SS, or seconds, then press Enter to jump and play"
              />
              {inputError && (
                <span className="absolute -bottom-4 left-0 text-[9px] text-red-700 dark:text-red-400 whitespace-nowrap">
                  Invalid time
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-2 text-xs text-red-700 dark:text-red-400">{error}</div>
      )}
    </div>
  );
}

function LayoutContent() {
  const location = useLocation();
  const isReplayPage = location.pathname === '/replay';

  // Theme management
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const stored = localStorage.getItem('theme');
    if (stored === 'light' || stored === 'dark') return stored;
    // Default to dark mode for existing users
    return 'dark';
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col border-r border-trident-border bg-trident-surface">
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-trident-border px-5 py-4">
          <img src="/trident.svg" alt="Trident" className="h-8 w-8" />
          <div>
            <h1 className="font-heading text-lg font-bold tracking-tight text-trident-text">
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

        {/* Theme toggle */}
        <div className="px-3 py-4 border-t border-trident-border dark:border-trident-border">
          <button
            onClick={toggleTheme}
            className="nav-link w-full justify-start"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
          </button>
        </div>

        {/* Status bar at bottom */}
        <ContainerStatusBar />
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden bg-trident-bg">
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>

        {/* Replay Control Bar - only show when NOT on the Replay page */}
        {!isReplayPage && <ReplayControlBar />}
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
