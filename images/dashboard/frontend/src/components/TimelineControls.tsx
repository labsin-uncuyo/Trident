import { useState, useCallback, useEffect } from 'react';
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react';

interface Props {
  duration: number;
  position: number;
  startTimeMs?: number;  // For converting absolute timestamps to offsets
  isPlaying: boolean;
  speed: number;
  onPlay: (speed?: number) => void;
  onPause: () => void;
  onSeek: (position: number) => void;
  onSpeedChange: (speed: number) => void;
  className?: string;
}

const SPEED_OPTIONS = [0.5, 1, 2, 5, 10, 25, 50, 100];

export function TimelineControls({
  duration,
  position,
  startTimeMs = 0,
  isPlaying,
  speed,
  onPlay,
  onPause,
  onSeek,
  onSpeedChange,
  className = '',
}: Props) {
  const progress = duration > 0 ? (position / duration) * 100 : 0;
  const [timeInput, setTimeInput] = useState('');
  const [inputError, setInputError] = useState(false);
  const [isUserEditing, setIsUserEditing] = useState(false);

  // Format time helper - needs to be defined before the useEffect
  const formatTime = useCallback((ms: number): string => {
    if (ms < 0) ms = 0;
    let displayMs = ms;
    if (startTimeMs > 0 && ms > 1000000000000) {
      displayMs = ms - startTimeMs;
    }
    const totalSeconds = Math.floor(displayMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }, [startTimeMs]);

  // Update the input when position changes externally (e.g., during playback)
  // But don't update while user is editing
  useEffect(() => {
    if (!isUserEditing) {
      setTimeInput(formatTime(position));
    }
  }, [position, isUserEditing, formatTime]);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = Number(e.target.value);
    onSeek(value);
  };

  const handleSkipBack = () => {
    onSeek(Math.max(0, position - 10000)); // Back 10 seconds
  };

  const handleSkipForward = () => {
    onSeek(Math.min(duration, position + 10000)); // Forward 10 seconds
  };

  // Parse time string in formats: "MM:SS", "HH:MM:SS", or "SS" (seconds only)
  const parseTimeToMs = useCallback((timeStr: string): number | null => {
    if (!timeStr.trim()) return null;

    // Try just seconds first (plain number)
    const secondsOnly = parseFloat(timeStr);
    if (!isNaN(secondsOnly)) {
      return Math.min(duration, Math.max(0, secondsOnly * 1000));
    }

    // Try HH:MM:SS or MM:SS format
    const parts = timeStr.split(':').map(p => parseInt(p, 10));

    if (parts.length === 2 && parts.every(p => !isNaN(p))) {
      // MM:SS format
      const [mins, secs] = parts;
      const totalMs = (mins * 60 + secs) * 1000;
      return Math.min(duration, Math.max(0, totalMs));
    }

    if (parts.length === 3 && parts.every(p => !isNaN(p))) {
      // HH:MM:SS format
      const [hrs, mins, secs] = parts;
      const totalMs = (hrs * 3600 + mins * 60 + secs) * 1000;
      return Math.min(duration, Math.max(0, totalMs));
    }

    return null;
  }, [duration]);

  const handleTimeInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setIsUserEditing(true);
    setTimeInput(e.target.value);
    setInputError(false);
  };

  const handleTimeInputSubmit = () => {
    const ms = parseTimeToMs(timeInput);
    if (ms !== null) {
      onSeek(ms);
      onPlay(speed); // Auto-play when seeking via text input
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
    setTimeInput(formatTime(position));
  };

  const handleTimeInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleTimeInputSubmit();
    } else if (e.key === 'Escape') {
      // Cancel editing on Escape
      setIsUserEditing(false);
      setInputError(false);
      setTimeInput(formatTime(position));
    }
  };

  return (
    <div className={`flex items-center gap-3 p-3 bg-trident-surface rounded-lg border border-trident-border ${className}`}>
      {/* Play/Pause button */}
      <button
        onClick={isPlaying ? onPause : () => onPlay(speed)}
        className="flex h-9 w-9 items-center justify-center rounded bg-trident-accent text-white hover:bg-trident-accent/80 transition-colors"
        aria-label={isPlaying ? 'Pause' : 'Play'}
        title={isPlaying ? 'Pause' : 'Play'}
      >
        {isPlaying ? <Pause size={16} /> : <Play size={16} />}
      </button>

      {/* Skip buttons */}
      <button
        onClick={handleSkipBack}
        className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-trident-text hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
        aria-label="Skip back 10s"
        title="Skip back 10s"
      >
        <SkipBack size={14} />
      </button>
      <button
        onClick={handleSkipForward}
        className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-trident-text hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
        aria-label="Skip forward 10s"
        title="Skip forward 10s"
      >
        <SkipForward size={14} />
      </button>

      {/* Timeline slider */}
      <div className="flex-1 flex flex-col gap-1">
        <input
          type="range"
          min={0}
          max={duration}
          value={position}
          onChange={handleSliderChange}
          className="w-full h-2 bg-trident-bg rounded-lg appearance-none cursor-pointer accent-trident-accent"
          style={{
            background: `linear-gradient(to right, var(--trident-accent) ${progress}%, var(--trident-border) ${progress}%)`,
          }}
        />
      </div>

      {/* Speed selector */}
      <select
        value={speed}
        onChange={(e) => onSpeedChange(Number(e.target.value))}
        className="px-2 py-1 text-xs bg-trident-bg border border-trident-border rounded text-trident-text focus:outline-none focus:border-trident-accent"
      >
        {SPEED_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}x
          </option>
        ))}
      </select>

      {/* Time display */}
      <span className="text-xs font-mono text-trident-muted min-w-[80px] text-right">
        {formatTime(position)} / {formatTime(duration)}
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
          className={`w-20 px-2 py-1 text-xs font-mono bg-trident-bg border rounded text-trident-text focus:outline-none ${
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
  );
}
