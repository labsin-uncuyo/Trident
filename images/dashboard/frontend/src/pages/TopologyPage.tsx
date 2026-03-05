import { useCallback, useEffect, useState } from 'react';
import {
  ReactFlow,
  type Node,
  type Edge,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Router,
  Server,
  Monitor,
  Shield,
  Skull,
} from 'lucide-react';
import { api } from '@/api';
import type { TopologyData, TopologyNode, ContainerState } from '@/types';

/* ── Types ──────────────────────────────────────────────────────── */

interface EdgeTraffic {
  bytes: number;
  mb: number;
  label: string;
}

/* ── Custom node component ────────────────────────────────────── */

const stateColor: Record<ContainerState, string> = {
  running: '#22c55e',
  stopped: '#6b7280',
  restarting: '#f59e0b',
  paused: '#f59e0b',
  exited: '#ef4444',
  dead: '#dc2626',
  unknown: '#4b5563',
};

const agentColor: Record<string, string> = {
  coder56: '#a78bfa',       // purple
  db_admin: '#34d399',      // green
  soc_god_server: '#38bdf8',    // sky
  soc_god_compromised: '#f472b6', // pink
};

const iconMap: Record<string, typeof Server> = {
  router: Router,
  server: Server,
  host: Monitor,
  defender: Shield,
  attacker: Skull,
};

function TopologyNodeComponent({ data }: NodeProps) {
  const nodeData = data as unknown as TopologyNode & { activeAgents?: string[] };
  const Icon = iconMap[nodeData.type] || Monitor;
  const color = stateColor[nodeData.state] || stateColor.unknown;
  const agents = nodeData.activeAgents ?? [];

  return (
    <div className="group relative">
      <Handle type="target" position={Position.Left} className="!bg-trident-accent" />
      <Handle type="source" position={Position.Right} className="!bg-trident-accent" />

      <div
        className="flex flex-col items-center rounded-xl border-2 bg-trident-surface px-5 py-4 shadow-xl transition-shadow hover:shadow-2xl"
        style={{ borderColor: color }}
      >
        {/* Status dot */}
        <div
          className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-2 border-trident-surface"
          style={{ backgroundColor: color }}
        />

        <Icon size={32} style={{ color }} />
        <span className="mt-2 text-sm font-semibold text-white">{nodeData.label}</span>

        <div className="mt-1.5 flex flex-wrap justify-center gap-1">
          {nodeData.ips.map((ip) => (
            <span key={ip} className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-[10px] text-trident-muted">
              {ip}
            </span>
          ))}
        </div>

        {/* Active agents */}
        {agents.length > 0 && (
          <div className="mt-2 flex flex-wrap justify-center gap-1">
            {agents.map((a) => (
              <span
                key={a}
                className="rounded-full px-2 py-0.5 text-[9px] font-semibold text-black"
                style={{ backgroundColor: agentColor[a] ?? '#94a3b8' }}
              >
                {a}
              </span>
            ))}
          </div>
        )}

        {/* Services tooltip on hover */}
        {nodeData.services.length > 0 && (
          <div className="mt-2 hidden max-w-[180px] flex-wrap gap-1 group-hover:flex">
            {nodeData.services.map((s) => (
              <span key={s} className="badge badge-info text-[9px]">{s}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { topologyNode: TopologyNodeComponent };

/* ── Page ──────────────────────────────────────────────────────── */

export function TopologyPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);

  const fetchTopology = useCallback(async () => {
    try {
      const [data, trafficResp, agentsResp] = await Promise.all([
        api.topology() as Promise<TopologyData>,
        api.topologyTraffic().catch(() => ({ edges: {} as Record<string, EdgeTraffic> })),
        api.topologyAgents().catch(() => ({ agents: {} as Record<string, string[]> })),
      ]);

      const trafficEdges = (trafficResp as { edges: Record<string, EdgeTraffic> }).edges ?? {};
      const activeAgents = (agentsResp as { agents: Record<string, string[]> }).agents ?? {};

      const flowNodes = data.nodes.map((n) => ({
        id: n.id,
        type: 'topologyNode' as const,
        position: n.position || { x: 0, y: 0 },
        data: { ...n, activeAgents: activeAgents[n.id] ?? [] } as unknown as Record<string, unknown>,
        draggable: true,
      })) satisfies Node[];

      const flowEdges = data.edges.map((e) => {
        const traffic = trafficEdges[e.id];
        const mb = traffic?.mb ?? 0;
        // Stroke width: 2 base + logarithmic scale, capped at 10
        const strokeWidth = mb > 0 ? Math.min(10, 2 + Math.log2(mb * 10 + 1)) : 2;
        // Redder tint for high-traffic edges
        const stroke = mb > 5 ? '#f97316' : mb > 1 ? '#60a5fa' : '#3b82f6';
        const edgeLabel = traffic ? `${e.label} · ${traffic.label}` : e.label;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: edgeLabel,
          animated: e.animated,
          style: { stroke, strokeWidth },
          labelStyle: { fill: '#9ca3af', fontSize: 11 },
          labelBgStyle: { fill: '#111827', fillOpacity: 0.9 },
          labelBgPadding: [6, 3] as [number, number],
          labelBgBorderRadius: 4,
        };
      }) satisfies Edge[];

      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (err) {
      console.error('Failed to load topology:', err);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges]);

  useEffect(() => {
    fetchTopology();
    const interval = setInterval(fetchTopology, 10_000);
    return () => clearInterval(interval);
  }, [fetchTopology]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-trident-accent border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="font-heading text-2xl font-bold text-white">Network Topology</h2>
          <p className="text-sm text-trident-muted">
            Trident cyber range — live container status · active agents · traffic flow
          </p>
        </div>
        <button onClick={fetchTopology} className="btn-ghost text-xs">
          Refresh
        </button>
      </div>

      <div className="flex-1 overflow-hidden rounded-xl border border-trident-border">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          proOptions={{ hideAttribution: true }}
          className="bg-trident-bg"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1e293b" />
          <Controls
            className="!border-trident-border !bg-trident-surface [&>button]:!border-trident-border [&>button]:!bg-trident-surface [&>button]:!text-trident-text [&>button:hover]:!bg-trident-border"
          />
          <MiniMap
            nodeStrokeColor={() => '#3b82f6'}
            nodeColor={() => '#1e293b'}
            maskColor="rgba(10, 14, 26, 0.8)"
            className="!border-trident-border !bg-trident-surface"
          />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="mt-3 flex items-center gap-4 text-xs text-trident-muted">
        {Object.entries(stateColor).map(([state, color]) => (
          <div key={state} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
            {state}
          </div>
        ))}
      </div>
    </div>
  );
}
