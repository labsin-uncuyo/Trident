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

  const formatTime = (ms: number): string => {
    if (ms < 0) ms = 0;
    // If this looks like an absolute timestamp (very large number), convert to offset from start
    let displayMs = ms;
    if (startTimeMs > 0 && ms > 1000000000000) {  // Absolute timestamp detected
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
  };

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
        className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-white hover:bg-white/10 transition-colors"
        aria-label="Skip back 10s"
        title="Skip back 10s"
      >
        <SkipBack size={14} />
      </button>
      <button
        onClick={handleSkipForward}
        className="flex h-7 w-7 items-center justify-center rounded text-trident-muted hover:text-white hover:bg-white/10 transition-colors"
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
    </div>
  );
}
