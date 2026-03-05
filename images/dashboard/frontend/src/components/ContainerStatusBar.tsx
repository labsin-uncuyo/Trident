import { useContainers } from '@/hooks/useContainers';
import type { ContainerState } from '@/types';

const stateColors: Record<ContainerState, string> = {
  running: 'bg-green-400',
  stopped: 'bg-gray-500',
  restarting: 'bg-yellow-400',
  paused: 'bg-yellow-400',
  exited: 'bg-red-400',
  dead: 'bg-red-600',
  unknown: 'bg-gray-600',
};

export function ContainerStatusBar() {
  const { containers, connected } = useContainers();

  return (
    <div className="border-t border-trident-border px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-trident-muted">
          Containers
        </span>
        <span
          className={`h-2 w-2 rounded-full ${
            connected ? 'bg-green-400' : 'bg-red-400'
          }`}
          title={connected ? 'WebSocket connected' : 'WebSocket disconnected'}
        />
      </div>
      <div className="space-y-1.5">
        {containers.map((c) => (
          <div key={c.name} className="flex items-center gap-2">
            <span
              className={`h-2 w-2 flex-shrink-0 rounded-full ${
                stateColors[c.state] || stateColors.unknown
              }`}
            />
            <span className="truncate text-xs text-trident-text">
              {c.name.replace('lab_', '')}
            </span>
            {c.health && (
              <span
                className={`ml-auto text-[10px] ${
                  c.health === 'healthy'
                    ? 'text-green-400'
                    : 'text-yellow-400'
                }`}
              >
                {c.health}
              </span>
            )}
          </div>
        ))}
        {containers.length === 0 && (
          <p className="text-xs text-trident-muted">No containers found</p>
        )}
      </div>
    </div>
  );
}
