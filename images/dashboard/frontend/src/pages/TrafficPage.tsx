import { useEffect, useState } from 'react';
import { Wifi, FileText, Clock, HardDrive, Construction } from 'lucide-react';
import { api } from '@/api';
import type { PcapFile } from '@/types';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function TrafficPage() {
  const [pcaps, setPcaps] = useState<PcapFile[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .pcaps()
      .then((data: any) => setPcaps(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));

    const interval = setInterval(() => {
      api.pcaps().then((data: any) => setPcaps(Array.isArray(data) ? data : [])).catch(() => {});
    }, 10_000);

    return () => clearInterval(interval);
  }, []);

  const totalSize = pcaps.reduce((sum, p) => sum + p.size_bytes, 0);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-6">
        <h2 className="font-heading text-2xl font-bold text-white">Traffic Capture</h2>
        <p className="text-sm text-trident-muted">
          PCAP files from router + server — {pcaps.length} files, {formatBytes(totalSize)} total
        </p>
      </div>

      {/* Stats row */}
      <div className="mb-6 grid grid-cols-4 gap-4">
        <div className="card text-center">
          <FileText size={24} className="mx-auto mb-2 text-trident-accent" />
          <p className="text-2xl font-bold text-white">{pcaps.length}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">PCAP Files</p>
        </div>
        <div className="card text-center">
          <HardDrive size={24} className="mx-auto mb-2 text-trident-accent" />
          <p className="text-2xl font-bold text-white">{formatBytes(totalSize)}</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Total Size</p>
        </div>
        <div className="card text-center">
          <Clock size={24} className="mx-auto mb-2 text-trident-accent" />
          <p className="text-2xl font-bold text-white">30s</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Rotation</p>
        </div>
        <div className="card text-center">
          <Wifi size={24} className="mx-auto mb-2 text-trident-accent" />
          <p className="text-2xl font-bold text-white">2</p>
          <p className="text-[10px] uppercase tracking-wider text-trident-muted">Interfaces</p>
        </div>
      </div>

      {/* Phase 2 placeholder panels */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        {['Protocol Distribution', 'Connection Timeline', 'Top Talkers'].map((title) => (
          <div key={title} className="card flex flex-col items-center justify-center py-12">
            <Construction size={32} className="mb-3 text-trident-muted opacity-40" />
            <p className="text-sm font-medium text-trident-muted">{title}</p>
            <p className="mt-1 text-xs text-trident-muted/60">Coming in Phase 2</p>
          </div>
        ))}
      </div>

      {/* PCAP file list */}
      <h3 className="mb-3 font-heading text-lg font-bold text-white">Capture Files</h3>
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-trident-accent border-t-transparent" />
          </div>
        ) : pcaps.length === 0 ? (
          <p className="py-8 text-center text-sm text-trident-muted">
            No PCAP files found — start the infrastructure with <code>make up</code>
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-trident-border text-xs uppercase tracking-wider text-trident-muted">
              <tr>
                <th className="px-3 py-2">Filename</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Modified</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-trident-border">
              {pcaps.map((p) => (
                <tr key={p.filename} className="hover:bg-trident-border/30">
                  <td className="px-3 py-2 font-mono text-xs text-trident-text">{p.filename}</td>
                  <td className="px-3 py-2 text-xs text-trident-muted">{formatBytes(p.size_bytes)}</td>
                  <td className="px-3 py-2 text-xs text-trident-muted">
                    {new Date(p.modified).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
