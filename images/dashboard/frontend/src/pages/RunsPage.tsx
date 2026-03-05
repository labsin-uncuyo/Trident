import { useEffect, useState } from 'react';
import { FolderOpen, Clock, FileText, ShieldAlert, CheckCircle } from 'lucide-react';
import { api } from '@/api';
import type { RunInfo } from '@/types';

export function RunsPage() {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .runs()
      .then((data: any) => setRuns(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-6">
        <h2 className="font-heading text-2xl font-bold text-white">Runs</h2>
        <p className="text-sm text-trident-muted">
          Experiment run history — {runs.length} runs found
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-trident-accent border-t-transparent" />
        </div>
      ) : runs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-trident-muted">
          <FolderOpen size={48} className="mb-4 opacity-30" />
          <p className="text-sm">No runs found</p>
          <p className="text-xs">Start the infrastructure with <code>make up</code></p>
        </div>
      ) : (
        <div className="grid gap-3">
          {runs.map((run) => (
            <div
              key={run.run_id}
              className={`card flex items-center gap-4 ${
                run.is_current ? 'border-trident-accent/50 ring-1 ring-trident-accent/20' : ''
              }`}
            >
              <FolderOpen
                size={20}
                className={run.is_current ? 'text-trident-accent' : 'text-trident-muted'}
              />

              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-white">{run.run_id}</span>
                  {run.is_current && (
                    <span className="badge badge-success">
                      <CheckCircle size={10} className="mr-1" />
                      Current
                    </span>
                  )}
                </div>
                {run.created && (
                  <div className="mt-1 flex items-center gap-1 text-xs text-trident-muted">
                    <Clock size={10} />
                    {new Date(run.created).toLocaleString()}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-3 text-xs text-trident-muted">
                <span className="flex items-center gap-1">
                  <FileText size={12} />
                  {run.has_pcaps ? 'PCAPs' : 'No PCAPs'}
                </span>
                <span className="flex items-center gap-1">
                  <ShieldAlert size={12} />
                  {run.has_alerts ? 'Alerts' : 'No Alerts'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
