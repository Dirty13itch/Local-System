"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import Link from "next/link";

// ─── Types ──────────────────────────────────────────────────────────────

interface MemoryStats {
  [tier: string]: { ready: boolean; count: number; health: string };
}

interface ModelInfo {
  alias: string;
  model_name: string;
  provider: string;
  node: string | null;
  mode: string;
  is_local: boolean;
  status: string;
}

interface ClusterService {
  name: string;
  status: string;
  uptime_hours?: number;
}

interface GallerySubject {
  name: string;
  status: string;
  images: { filename: string; url: string; prompt?: string }[];
  refs: string[];
  processed_at?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const color =
    status === "ok" || status === "online" || status === "healthy"
      ? "bg-green-500"
      : status === "degraded" || status === "warning"
        ? "bg-yellow-500"
        : "bg-red-500";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d ${h % 24}h`;
  return `${h}h`;
}

// ─── Dashboard ──────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [health, setHealth] = useState<{
    status: string;
    uptime_seconds: number;
  } | null>(null);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [collections, setCollections] = useState<
    { name: string; points_count: number }[]
  >([]);
  const [clusterHealth, setClusterHealth] = useState<{
    services: ClusterService[];
  } | null>(null);
  const [galleryData, setGalleryData] = useState<{
    subjects: GallerySubject[];
    total_images: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchAll = useCallback(async () => {
    try {
      const [healthRes, memRes, modelsRes, colRes, clusterRes, galleryRes] =
        await Promise.allSettled([
          api.health(),
          api.getMemoryStats(),
          api.getModelInfo(),
          api.listCollections(),
          api.clusterHealth(),
          fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700"}/v1/generate/gallery`).then(r => r.json()),
        ]);

      if (healthRes.status === "fulfilled") setHealth(healthRes.value as any);
      if (memRes.status === "fulfilled") setMemoryStats(memRes.value as any);
      if (modelsRes.status === "fulfilled")
        setModels((modelsRes.value as any)?.models || []);
      if (colRes.status === "fulfilled") setCollections((colRes.value as any) || []);
      if (clusterRes.status === "fulfilled")
        setClusterHealth(clusterRes.value as any);
      if (galleryRes.status === "fulfilled")
        setGalleryData(galleryRes.value as any);

      setLastRefresh(new Date());
    } catch (e) {
      console.error("Dashboard fetch failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--text-secondary)]">
        Loading dashboard...
      </div>
    );
  }

  const totalMemoryEntries = memoryStats
    ? Object.values(memoryStats).reduce((sum, t) => sum + (t.count || 0), 0)
    : 0;

  const totalVectorPoints = collections.reduce(
    (sum, c) => sum + (c.points_count || 0),
    0
  );

  const localModels = models.filter((m) => m.is_local);
  const onlineModels = localModels.filter((m) => m.status === "online");

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Command Center
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Sovereign Cognitive Architecture — System Overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[var(--text-secondary)]">
            Last refresh: {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            onClick={fetchAll}
            className="px-3 py-1.5 text-xs rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--border)] transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Quick Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Gateway"
          value={health?.status === "ok" ? "Online" : "Offline"}
          sub={health ? formatUptime(health.uptime_seconds) : "—"}
          status={health?.status || "error"}
        />
        <StatCard
          label="Local Models"
          value={`${onlineModels.length}/${localModels.length}`}
          sub="online"
          status={
            onlineModels.length === localModels.length ? "ok" : "warning"
          }
        />
        <StatCard
          label="Memory Entries"
          value={totalMemoryEntries.toLocaleString()}
          sub={`${Object.keys(memoryStats || {}).length} tiers`}
          status="ok"
        />
        <StatCard
          label="Vector Points"
          value={totalVectorPoints.toLocaleString()}
          sub={`${collections.length} collections`}
          status="ok"
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Memory Tiers */}
        <DashCard
          title="Memory System"
          href="/memory"
          linkLabel="Open Memory"
        >
          {memoryStats ? (
            <div className="space-y-2">
              {Object.entries(memoryStats).map(([tier, info]) => (
                <div
                  key={tier}
                  className="flex items-center justify-between py-1"
                >
                  <div className="flex items-center gap-2">
                    <StatusDot status={info.health} />
                    <span className="text-sm capitalize">{tier}</span>
                  </div>
                  <span className="text-sm font-mono text-[var(--text-secondary)]">
                    {info.count.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              Memory service unavailable
            </p>
          )}
        </DashCard>

        {/* Models */}
        <DashCard
          title="Inference Models"
          href="/models"
          linkLabel="Open Models"
        >
          <div className="space-y-2">
            {models
              .filter((m) => (m.mode === "chat" || m.mode === null) && m.is_local)
              .map((m) => (
                <div
                  key={m.alias}
                  className="flex items-center justify-between py-1"
                >
                  <div className="flex items-center gap-2">
                    <StatusDot status={m.status} />
                    <span className="text-sm">{m.alias}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.node && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">
                        {m.node}
                      </span>
                    )}
                    <span className="text-xs text-[var(--text-secondary)] font-mono max-w-[180px] truncate">
                      {m.model_name}
                    </span>
                  </div>
                </div>
              ))}
            {models.filter((m) => m.mode !== "chat" && m.mode !== null && m.is_local).length >
              0 && (
              <div className="pt-2 border-t border-[var(--border)]">
                <p className="text-xs text-[var(--text-secondary)] mb-1">
                  Utility Models
                </p>
                {models
                  .filter((m) => m.mode !== "chat" && m.mode !== null && m.is_local)
                  .map((m) => (
                    <div
                      key={m.alias}
                      className="flex items-center justify-between py-0.5"
                    >
                      <div className="flex items-center gap-2">
                        <StatusDot status={m.status} />
                        <span className="text-xs">{m.alias}</span>
                      </div>
                      <span className="text-xs text-[var(--text-secondary)]">
                        {m.node || "—"}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </DashCard>

        {/* Collections */}
        <DashCard
          title="Knowledge Base"
          href="/documents"
          linkLabel="Open Knowledge"
        >
          <div className="space-y-2">
            {collections.map((c) => (
              <div
                key={c.name}
                className="flex items-center justify-between py-1"
              >
                <span className="text-sm font-mono">{c.name}</span>
                <span className="text-sm text-[var(--text-secondary)]">
                  {c.points_count.toLocaleString()} points
                </span>
              </div>
            ))}
          </div>
        </DashCard>

        {/* Cluster Services */}
        <DashCard
          title="Cluster Services"
          href="/nodes"
          linkLabel="Open Nodes"
        >
          {clusterHealth?.services ? (
            <div className="space-y-2">
              {clusterHealth.services.map((svc) => (
                <div
                  key={svc.name}
                  className="flex items-center justify-between py-1"
                >
                  <div className="flex items-center gap-2">
                    <StatusDot status={svc.status} />
                    <span className="text-sm">{svc.name}</span>
                  </div>
                  {svc.uptime_hours !== undefined && (
                    <span className="text-xs text-[var(--text-secondary)]">
                      {svc.uptime_hours > 24
                        ? `${Math.floor(svc.uptime_hours / 24)}d`
                        : `${Math.round(svc.uptime_hours)}h`}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              Cluster health unavailable — check Gateway
            </p>
          )}
        </DashCard>
      </div>

      {/* Recent Generations */}
      {galleryData && galleryData.subjects.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                Recent Generations
              </h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">
                {galleryData.total_images} images
              </span>
            </div>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700"}/gallery`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
            >
              Open Gallery &rarr;
            </a>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {galleryData.subjects
              .filter((s) => s.status === "done" && s.images.length > 0)
              .flatMap((s) =>
                s.images.slice(0, 2).map((img) => ({
                  ...img,
                  subject: s.name,
                }))
              )
              .slice(0, 12)
              .map((img, i) => (
                <a
                  key={`${img.subject}-${img.filename}-${i}`}
                  href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700"}/gallery`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group relative aspect-[3/4] rounded-lg overflow-hidden border border-[var(--border)] bg-[var(--bg-tertiary)]"
                >
                  <img
                    src={img.url}
                    alt={img.subject}
                    className="w-full h-full object-cover transition-transform group-hover:scale-105"
                    loading="lazy"
                  />
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <p className="text-xs text-white truncate">
                      {img.subject.replace(/_/g, " ")}
                    </p>
                  </div>
                </a>
              ))}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <QuickAction href="/generate" label="Generate Studio" icon="G" />
        <QuickAction
          href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700"}/gallery`}
          label="Content Gallery"
          icon="📷"
          external
        />
        <QuickAction href="/memory" label="Search Memory" icon="W" />
        <QuickAction href="/documents" label="Ingest Document" icon="K" />
        <QuickAction href="/chat" label="Chat" icon="C" />
      </div>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  status,
}: {
  label: string;
  value: string;
  sub: string;
  status: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="flex items-center gap-2 mb-2">
        <StatusDot status={status} />
        <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider">
          {label}
        </span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs text-[var(--text-secondary)] mt-1">{sub}</p>
    </div>
  );
}

function DashCard({
  title,
  href,
  linkLabel,
  children,
}: {
  title: string;
  href: string;
  linkLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          {title}
        </h2>
        <Link
          href={href}
          className="text-xs text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
        >
          {linkLabel} &rarr;
        </Link>
      </div>
      {children}
    </div>
  );
}

function QuickAction({
  href,
  label,
  icon,
  external,
}: {
  href: string;
  label: string;
  icon: string;
  external?: boolean;
}) {
  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
      >
        <span className="w-8 h-8 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center text-sm font-mono text-[var(--accent)]">
          {icon}
        </span>
        <span className="text-sm">{label}</span>
      </a>
    );
  }
  return (
    <Link
      href={href}
      className="flex items-center gap-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
    >
      <span className="w-8 h-8 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center text-sm font-mono text-[var(--accent)]">
        {icon}
      </span>
      <span className="text-sm">{label}</span>
    </Link>
  );
}
