"use client";

import { useEffect, useState, useCallback } from "react";
import {
  api,
  type NodeStatus,
  type NodesResponse,
  type ClusterHealth,
} from "@/lib/api";

// ─── Service-to-Node mapping ─────────────────────────────────────────────

const SERVICE_MAP: Record<string, { node: string; label: string }> = {
  litellm: { node: "VAULT", label: "LiteLLM" },
  memory: { node: "DEV", label: "Memory" },
  mind: { node: "DEV", label: "MIND" },
  perception: { node: "DEV", label: "Perception" },
  vllm_reasoning: { node: "FOUNDRY", label: "Reasoning (Qwen3-32B)" },
  vllm_coding: { node: "FOUNDRY", label: "Coding (GLM-4.7)" },
  vllm_creative: { node: "FOUNDRY", label: "Creative (Qwen3-8B)" },
  vllm_embedding: { node: "DEV", label: "Embedding" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────

function formatUptime(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  const d = Math.floor(hours / 24);
  const h = Math.floor(hours % 24);
  if (d > 0) return `${d}d ${h}h`;
  return `${h}h`;
}

function formatGB(gb: number): string {
  return gb.toFixed(1);
}

function formatMBtoGB(mb: number): string {
  return (mb / 1024).toFixed(1);
}

function pct(used: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((used / total) * 100);
}

function utilizationColor(percent: number): string {
  if (percent < 50) return "var(--success)";
  if (percent < 80) return "var(--warning)";
  return "var(--error)";
}

function tempColor(temp: number): string {
  if (temp < 60) return "var(--success)";
  if (temp < 80) return "var(--warning)";
  return "var(--error)";
}

function timeSince(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function getServicesByNode(
  nodeName: string,
  clusterHealth: ClusterHealth | null
): Array<{ key: string; label: string; healthy: boolean }> {
  const results: Array<{ key: string; label: string; healthy: boolean }> = [];
  for (const [key, mapping] of Object.entries(SERVICE_MAP)) {
    if (mapping.node === nodeName) {
      const svcHealth = clusterHealth?.[key];
      const healthy = svcHealth ? !("error" in svcHealth) : false;
      results.push({ key, label: mapping.label, healthy });
    }
  }
  return results;
}

// ─── Progress Bar Component ──────────────────────────────────────────────

function UsageBar({
  label,
  used,
  total,
  unit,
  colorByPercent = false,
}: {
  label: string;
  used: number;
  total: number;
  unit: string;
  colorByPercent?: boolean;
}) {
  const percent = pct(used, total);
  const barColor = colorByPercent ? utilizationColor(percent) : "var(--accent)";

  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-[var(--text-secondary)]">{label}</span>
        <span className="text-xs font-mono text-[var(--text-secondary)]">
          {unit === "%" ? `${percent}%` : `${used} / ${total} ${unit}`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--bg-primary)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${Math.min(percent, 100)}%`, background: barColor }}
        />
      </div>
    </div>
  );
}

// ─── GPU Card Component ──────────────────────────────────────────────────

function GpuCard({
  gpu,
}: {
  gpu: NodeStatus["gpus"][number];
}) {
  const vramUsedGB = formatMBtoGB(gpu.vram_used_mb);
  const vramTotalGB = formatMBtoGB(gpu.vram_total_mb);
  const vramPct = pct(gpu.vram_used_mb, gpu.vram_total_mb);

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-primary)] p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--text-primary)] truncate">
          GPU {gpu.index}: {gpu.name}
        </span>
      </div>

      {/* Utilization */}
      <div className="w-full">
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs text-[var(--text-secondary)]">Util</span>
          <span className="text-xs font-mono text-[var(--text-secondary)]">
            {gpu.utilization_percent}%
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${gpu.utilization_percent}%`,
              background: utilizationColor(gpu.utilization_percent),
            }}
          />
        </div>
      </div>

      {/* VRAM */}
      <div className="w-full">
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs text-[var(--text-secondary)]">VRAM</span>
          <span className="text-xs font-mono text-[var(--text-secondary)]">
            {vramUsedGB} / {vramTotalGB} GB
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${vramPct}%`,
              background: utilizationColor(vramPct),
            }}
          />
        </div>
      </div>

      {/* Temp + Power row */}
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: tempColor(gpu.temperature_c) }}
          />
          <span className="font-mono" style={{ color: tempColor(gpu.temperature_c) }}>
            {gpu.temperature_c}°C
          </span>
        </span>
        <span className="text-[var(--text-secondary)] font-mono">
          {gpu.power_watts}W
        </span>
      </div>
    </div>
  );
}

// ─── Node Card Component ─────────────────────────────────────────────────

function NodeCard({
  node,
  services,
}: {
  node: NodeStatus;
  services: Array<{ key: string; label: string; healthy: boolean }>;
}) {
  const statusColor = node.online ? "var(--success)" : "var(--error)";
  const hasMultiGPU = node.gpus.length > 3;

  return (
    <div
      className={`rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-4 ${
        hasMultiGPU ? "md:col-span-2" : ""
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: statusColor }}
          />
          <div>
            <h3 className="font-semibold text-lg leading-none">{node.name}</h3>
            <span className="text-xs text-[var(--text-secondary)] font-mono">
              {node.ip}
            </span>
          </div>
        </div>
        <span className="text-xs text-[var(--text-secondary)]">
          up {formatUptime(node.uptime_hours)}
        </span>
      </div>

      {/* CPU / RAM / Disk */}
      {node.online && (
        <div className="space-y-2.5">
          <UsageBar
            label="CPU"
            used={node.cpu_percent}
            total={100}
            unit="%"
            colorByPercent
          />
          <UsageBar
            label="RAM"
            used={Number(formatGB(node.ram_used_gb))}
            total={Number(formatGB(node.ram_total_gb))}
            unit="GB"
            colorByPercent
          />
          <UsageBar
            label="Disk"
            used={Number(formatGB(node.disk_used_gb))}
            total={Number(formatGB(node.disk_total_gb))}
            unit="GB"
            colorByPercent
          />
        </div>
      )}

      {/* GPUs */}
      {node.gpus.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
            GPUs ({node.gpus.length})
          </h4>
          <div
            className={`grid gap-2 ${
              node.gpus.length > 2 ? "grid-cols-2 lg:grid-cols-3" : "grid-cols-1"
            }`}
          >
            {node.gpus.map((gpu) => (
              <GpuCard key={gpu.index} gpu={gpu} />
            ))}
          </div>
        </div>
      )}

      {/* Services */}
      {services.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
            Services
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {services.map((svc) => (
              <span
                key={svc.key}
                className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--bg-primary)]"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{
                    background: svc.healthy ? "var(--success)" : "var(--error)",
                  }}
                />
                {svc.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Offline state */}
      {!node.online && (
        <div className="text-center py-4 text-[var(--text-secondary)] text-sm">
          Node offline
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────

export default function NodesPage() {
  const [nodesData, setNodesData] = useState<NodesResponse | null>(null);
  const [clusterHealth, setClusterHealth] = useState<ClusterHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [, setTick] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const [nodesResp, healthResp] = await Promise.allSettled([
        api.getNodeStatus(),
        api.clusterHealth(),
      ]);

      if (nodesResp.status === "fulfilled") {
        setNodesData(nodesResp.value);
        setLastUpdated(nodesResp.value.timestamp || new Date().toISOString());
        setError(null);
      } else {
        setError("Failed to fetch node status");
      }

      if (healthResp.status === "fulfilled") {
        setClusterHealth(healthResp.value);
      }
    } catch {
      setError("Connection to gateway failed");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch + 30s auto-refresh
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Tick every second to update "X seconds ago" display
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // ─── Derived stats ───────────────────────────────────────────────────

  const nodes = nodesData?.nodes || [];
  const onlineCount = nodes.filter((n) => n.online).length;
  const totalGpus = nodes.reduce((sum, n) => sum + n.gpus.length, 0);
  const totalVramGB = nodes.reduce(
    (sum, n) =>
      sum + n.gpus.reduce((gs, g) => gs + g.vram_total_mb / 1024, 0),
    0
  );
  const usedVramGB = nodes.reduce(
    (sum, n) =>
      sum + n.gpus.reduce((gs, g) => gs + g.vram_used_mb / 1024, 0),
    0
  );
  const totalRamGB = nodes.reduce((sum, n) => sum + n.ram_total_gb, 0);
  const usedRamGB = nodes.reduce((sum, n) => sum + n.ram_used_gb, 0);

  const clusterStatus =
    onlineCount === nodes.length
      ? "healthy"
      : onlineCount > 0
        ? "degraded"
        : "offline";

  const statusColors: Record<string, string> = {
    healthy: "var(--success)",
    degraded: "var(--warning)",
    offline: "var(--error)",
  };

  // ─── Render ────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Cluster Nodes</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Infrastructure status across the Athanor cluster
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-[var(--text-secondary)]">
              Updated {timeSince(lastUpdated)}
            </span>
          )}
          <button
            onClick={() => {
              setLoading(true);
              fetchData();
            }}
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent)] transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Loading State */}
      {loading && !nodesData && (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-3">
            <div className="relative w-10 h-10">
              <div className="absolute inset-0 border-2 border-[var(--border)] rounded-full" />
              <div className="absolute inset-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            </div>
            <span className="text-sm text-[var(--text-secondary)]">
              Connecting to cluster...
            </span>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && !nodesData && (
        <div className="rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-6 text-center">
          <p className="text-[var(--error)] mb-2">{error}</p>
          <p className="text-sm text-[var(--text-secondary)]">
            The gateway at {typeof window !== "undefined" ? api.toString() : ""} may be unreachable.
          </p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              fetchData();
            }}
            className="mt-4 text-xs px-4 py-2 rounded-md bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] hover:border-[var(--accent)] transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Dashboard Content */}
      {nodesData && (
        <>
          {/* Overview Strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {/* Nodes Online */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: statusColors[clusterStatus] }}
                />
                <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider">
                  Nodes
                </span>
              </div>
              <div className="text-2xl font-bold font-mono">
                {onlineCount}
                <span className="text-sm text-[var(--text-secondary)] font-normal">
                  {" "}/ {nodes.length}
                </span>
              </div>
              <span
                className="text-xs capitalize"
                style={{ color: statusColors[clusterStatus] }}
              >
                {clusterStatus}
              </span>
            </div>

            {/* Total GPUs */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                GPUs
              </span>
              <div className="text-2xl font-bold font-mono">{totalGpus}</div>
              <span className="text-xs text-[var(--text-secondary)]">
                across cluster
              </span>
            </div>

            {/* VRAM */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                VRAM
              </span>
              <div className="text-2xl font-bold font-mono">
                {formatGB(usedVramGB)}
                <span className="text-sm text-[var(--text-secondary)] font-normal">
                  {" "}/ {formatGB(totalVramGB)} GB
                </span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-[var(--bg-primary)] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${pct(usedVramGB, totalVramGB)}%`,
                    background: utilizationColor(pct(usedVramGB, totalVramGB)),
                  }}
                />
              </div>
            </div>

            {/* RAM */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                Cluster RAM
              </span>
              <div className="text-2xl font-bold font-mono">
                {formatGB(usedRamGB)}
                <span className="text-sm text-[var(--text-secondary)] font-normal">
                  {" "}/ {formatGB(totalRamGB)} GB
                </span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-[var(--bg-primary)] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${pct(usedRamGB, totalRamGB)}%`,
                    background: utilizationColor(pct(usedRamGB, totalRamGB)),
                  }}
                />
              </div>
            </div>
          </div>

          {/* Node Cards Grid */}
          <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
            {nodes.map((node) => (
              <NodeCard
                key={node.name}
                node={node}
                services={getServicesByNode(node.name, clusterHealth)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
