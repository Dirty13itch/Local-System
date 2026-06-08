"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, WorkingContext } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab = "overview" | "working" | "search" | "explorer" | "store";

interface TierInfo {
  id: string;
  name: string;
  backend: string;
  color: string;
  colorBg: string;
  description: string;
}

interface MemoryStats {
  working: { count: number; status: string };
  episodic: { count: number; status: string };
  semantic: { count: number; status: string };
  procedural: { count: number; status: string };
  resource: { count: number; status: string };
  vault: { count: number; status: string };
}

interface SearchResult {
  content: string;
  tier?: string;
  source?: string;
  confidence?: number;
  score?: number;
  timestamp?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

interface StoreResponse {
  success?: boolean;
  id?: string;
  error?: string;
  detail?: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700";

const TIERS: TierInfo[] = [
  {
    id: "working",
    name: "Working",
    backend: "Redis",
    color: "text-blue-400",
    colorBg: "bg-blue-500/20",
    description: "Ephemeral active conversation context. Tracks current task, priorities, and unresolved questions. Cleared between sessions.",
  },
  {
    id: "episodic",
    name: "Episodic",
    backend: "Qdrant",
    color: "text-purple-400",
    colorBg: "bg-purple-500/20",
    description: "Timestamped events and session logs. Records what happened, when, and outcomes. Consolidates to Vault over time.",
  },
  {
    id: "semantic",
    name: "Semantic",
    backend: "Neo4j",
    color: "text-green-400",
    colorBg: "bg-green-500/20",
    description: "Knowledge graph with entity relationships. Stores facts, connections, and structured knowledge about the system and world.",
  },
  {
    id: "procedural",
    name: "Procedural",
    backend: "PostgreSQL",
    color: "text-orange-400",
    colorBg: "bg-orange-500/20",
    description: "How-to procedures and operational recipes. Step-by-step instructions for deployment, troubleshooting, and maintenance.",
  },
  {
    id: "resource",
    name: "Resource",
    backend: "Qdrant + Meilisearch",
    color: "text-cyan-400",
    colorBg: "bg-cyan-500/20",
    description: "Ingested documents, codebase chunks, and reference materials. Hybrid vector + full-text search for RAG retrieval.",
  },
  {
    id: "vault",
    name: "Vault",
    backend: "PostgreSQL + Qdrant",
    color: "text-yellow-400",
    colorBg: "bg-yellow-500/20",
    description: "Long-term archive of important memories. Consolidated from episodic and working tiers. Permanent knowledge storage.",
  },
];

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "working", label: "Working Memory" },
  { id: "search", label: "Deep Search" },
  { id: "explorer", label: "Tier Explorer" },
  { id: "store", label: "Store" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function tierColor(tierId: string): { text: string; bg: string } {
  const tier = TIERS.find((t) => t.id === tierId);
  return tier
    ? { text: tier.color, bg: tier.colorBg }
    : { text: "text-gray-400", bg: "bg-gray-500/20" };
}

function truncate(text: string, maxLen: number): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}

function timeAgo(timestamp: string | number | undefined): string {
  if (!timestamp) return "";
  const t = typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp * 1000;
  if (isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function formatConfidence(value: number | undefined): string {
  if (value === undefined || value === null) return "--";
  return `${(value * 100).toFixed(0)}%`;
}

// ─── API Helpers ──────────────────────────────────────────────────────────────

async function fetchMemoryStats(): Promise<MemoryStats | null> {
  try {
    const resp = await fetch(`${BASE_URL}/v1/memory/stats`);
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}

async function storeMemory(params: {
  content: string;
  tier: string;
  source?: string;
  tags?: string[];
}): Promise<StoreResponse> {
  try {
    const resp = await fetch(`${BASE_URL}/v1/memory/store`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  } catch (e) {
    return { error: String(e) };
  }
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function MemoryPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [collections, setCollections] = useState<Array<{ name: string; vectors_count?: number; points_count?: number }>>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const loadStats = useCallback(async () => {
    try {
      const [memStats, cols] = await Promise.all([
        fetchMemoryStats(),
        api.listCollections(),
      ]);
      if (memStats) setStats(memStats);
      setCollections(cols);
      setLastRefresh(new Date());
    } catch {
      // Silently handle errors
    }
    setStatsLoading(false);
  }, []);

  // Initial load
  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(loadStats, 30_000);
    return () => clearInterval(interval);
  }, [loadStats]);

  // Get tier counts — merge stats API with collection data
  function getTierCount(tierId: string): number {
    if (stats) {
      const tierStat = stats[tierId as keyof MemoryStats];
      if (tierStat && typeof tierStat === "object" && "count" in tierStat) {
        return tierStat.count;
      }
    }
    // Fallback to collection data for Qdrant-backed tiers
    if (tierId === "episodic") {
      const col = collections.find((c) => c.name === "episodic");
      return col?.points_count ?? col?.vectors_count ?? 0;
    }
    if (tierId === "resource") {
      const col = collections.find((c) => c.name === "resources");
      return col?.points_count ?? col?.vectors_count ?? 0;
    }
    if (tierId === "vault") {
      const col = collections.find((c) => c.name === "knowledge_vault");
      return col?.points_count ?? col?.vectors_count ?? 0;
    }
    return 0;
  }

  function getTierStatus(tierId: string): string {
    if (stats) {
      const tierStat = stats[tierId as keyof MemoryStats];
      if (tierStat && typeof tierStat === "object" && "status" in tierStat) {
        return tierStat.status;
      }
    }
    return "unknown";
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Memory System</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            6-tier cognitive memory — Working, Episodic, Semantic, Procedural, Resource, Vault
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[var(--text-secondary)]">
            Updated {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            onClick={() => { setStatsLoading(true); loadStats(); }}
            className="text-xs px-3 py-1.5 rounded border border-[var(--border)] hover:border-[var(--accent)] transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Overview stat cards — always visible */}
      <TierOverviewStrip
        getTierCount={getTierCount}
        getTierStatus={getTierStatus}
        loading={statsLoading}
      />

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
              tab === t.id
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && (
        <OverviewTab
          getTierCount={getTierCount}
          getTierStatus={getTierStatus}
          collections={collections}
        />
      )}
      {tab === "working" && <WorkingMemoryTab />}
      {tab === "search" && <DeepSearchTab />}
      {tab === "explorer" && <TierExplorerTab getTierCount={getTierCount} />}
      {tab === "store" && <StoreTab />}
    </div>
  );
}

// ─── Tier Overview Strip ──────────────────────────────────────────────────────

function TierOverviewStrip({
  getTierCount,
  getTierStatus,
  loading,
}: {
  getTierCount: (id: string) => number;
  getTierStatus: (id: string) => string;
  loading: boolean;
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {TIERS.map((tier) => {
        const count = getTierCount(tier.id);
        const status = getTierStatus(tier.id);
        const statusDot =
          status === "ok" || status === "healthy"
            ? "bg-green-500"
            : status === "unknown"
              ? "bg-gray-500"
              : "bg-orange-500";

        return (
          <div
            key={tier.id}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3"
          >
            <div className="flex items-center justify-between mb-2">
              <span className={`text-xs font-semibold ${tier.color}`}>
                {tier.name}
              </span>
              <span className={`w-2 h-2 rounded-full ${statusDot}`} />
            </div>
            <p className="text-2xl font-bold font-mono">
              {loading ? (
                <span className="text-[var(--text-secondary)] animate-pulse">--</span>
              ) : (
                count.toLocaleString()
              )}
            </p>
            <p className="text-[10px] text-[var(--text-secondary)] mt-1 font-mono">
              {tier.backend}
            </p>
          </div>
        );
      })}
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({
  getTierCount,
  getTierStatus,
  collections,
}: {
  getTierCount: (id: string) => number;
  getTierStatus: (id: string) => string;
  collections: Array<{ name: string; vectors_count?: number; points_count?: number }>;
}) {
  const totalEntries = TIERS.reduce((sum, tier) => sum + getTierCount(tier.id), 0);

  return (
    <div className="space-y-6">
      {/* Architecture summary */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5">
        <h2 className="text-lg font-semibold mb-3">Memory Architecture</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-[var(--text-secondary)]">Total entries</span>
              <span className="font-mono font-bold">{totalEntries.toLocaleString()}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--text-secondary)]">Active tiers</span>
              <span className="font-mono font-bold">
                {TIERS.filter((t) => {
                  const s = getTierStatus(t.id);
                  return s === "ok" || s === "healthy";
                }).length}
                {" / "}
                {TIERS.length}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--text-secondary)]">Consolidation</span>
              <span className="font-mono text-xs">Daily 3:00 AM</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-[var(--text-secondary)]">Perception watchers</span>
              <span className="font-mono text-xs">2 active</span>
            </div>
          </div>
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-[var(--text-secondary)]">Data Flow</h3>
            <div className="text-xs text-[var(--text-secondary)] space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-blue-400">Working</span>
                <span>-&gt;</span>
                <span className="text-purple-400">Episodic</span>
                <span className="text-[10px]">(session end)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-purple-400">Episodic</span>
                <span>-&gt;</span>
                <span className="text-yellow-400">Vault</span>
                <span className="text-[10px]">(consolidation)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-cyan-400">Resource</span>
                <span>&lt;-</span>
                <span>Perception</span>
                <span className="text-[10px]">(file watchers)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-green-400">Semantic</span>
                <span>&lt;-</span>
                <span>Extraction</span>
                <span className="text-[10px]">(entity/relation)</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tier detail cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {TIERS.map((tier) => {
          const count = getTierCount(tier.id);
          const status = getTierStatus(tier.id);
          return (
            <div
              key={tier.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-semibold ${tier.color}`}>
                    {tier.name}
                  </span>
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${tier.colorBg} ${tier.color}`}>
                    {tier.backend}
                  </span>
                </div>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded ${
                    status === "ok" || status === "healthy"
                      ? "bg-green-500/20 text-green-400"
                      : status === "unknown"
                        ? "bg-gray-500/20 text-gray-400"
                        : "bg-orange-500/20 text-orange-400"
                  }`}
                >
                  {status === "ok" || status === "healthy" ? "healthy" : status}
                </span>
              </div>
              <p className="text-xs text-[var(--text-secondary)] mb-3 leading-relaxed">
                {tier.description}
              </p>
              <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]">
                <span className="text-xs text-[var(--text-secondary)]">Entries</span>
                <span className="font-mono font-bold text-sm">{count.toLocaleString()}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Qdrant collections */}
      {collections.length > 0 && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h3 className="text-sm font-semibold mb-3">Qdrant Collections</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {collections.map((col) => (
              <div
                key={col.name}
                className="rounded border border-[var(--border)] bg-[var(--bg-primary)] p-3"
              >
                <p className="text-xs font-mono font-medium mb-1">{col.name}</p>
                <p className="text-lg font-bold font-mono">
                  {(col.points_count ?? col.vectors_count ?? 0).toLocaleString()}
                </p>
                <p className="text-[10px] text-[var(--text-secondary)]">vectors</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Working Memory Tab ───────────────────────────────────────────────────────

function WorkingMemoryTab() {
  const [working, setWorking] = useState<WorkingContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadWorking = useCallback(async () => {
    try {
      const data = await api.getWorkingMemory();
      setWorking(data);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadWorking();
    const interval = setInterval(loadWorking, 10_000);
    return () => clearInterval(interval);
  }, [loadWorking]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-[var(--text-secondary)]">
        <span className="animate-pulse">Loading working memory...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-6 text-center">
        <p className="text-[var(--error)] text-sm mb-2">Failed to load working memory</p>
        <p className="text-xs text-[var(--text-secondary)]">{error}</p>
        <button
          onClick={() => { setLoading(true); loadWorking(); }}
          className="mt-3 text-xs px-3 py-1.5 rounded border border-[var(--border)] hover:border-[var(--accent)] transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const hasTask = working?.active_task && working.active_task !== "None" && working.active_task !== "";
  const hasPriorities = working?.active_priorities && working.active_priorities.length > 0;
  const hasQuestions = working?.unresolved_questions && working.unresolved_questions.length > 0;
  const isEmpty = !hasTask && !hasPriorities && !hasQuestions;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Working Memory</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Real-time ephemeral context from Redis. Refreshes every 10 seconds.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-xs text-blue-400">Live</span>
        </div>
      </div>

      {isEmpty ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
          <p className="text-lg text-[var(--text-secondary)] mb-2">Working memory is empty</p>
          <p className="text-xs text-[var(--text-secondary)]">
            No active task, priorities, or unresolved questions. This is normal between sessions.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Active Task */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <h3 className="text-sm font-semibold text-blue-400">Active Task</h3>
            </div>
            {hasTask ? (
              <p className="text-sm leading-relaxed">{working!.active_task}</p>
            ) : (
              <p className="text-sm text-[var(--text-secondary)] italic">No active task</p>
            )}
          </div>

          {/* Priorities */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <h3 className="text-sm font-semibold text-blue-400">
                Priorities
                {hasPriorities && (
                  <span className="ml-1.5 font-normal text-[var(--text-secondary)]">
                    ({working!.active_priorities.length})
                  </span>
                )}
              </h3>
            </div>
            {hasPriorities ? (
              <ul className="space-y-2">
                {working!.active_priorities.map((p, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="text-xs text-[var(--text-secondary)] font-mono mt-0.5">
                      {i + 1}.
                    </span>
                    <span className="leading-relaxed">{p}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--text-secondary)] italic">No priorities set</p>
            )}
          </div>

          {/* Unresolved Questions */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
              <h3 className="text-sm font-semibold text-orange-400">
                Unresolved
                {hasQuestions && (
                  <span className="ml-1.5 font-normal text-[var(--text-secondary)]">
                    ({working!.unresolved_questions.length})
                  </span>
                )}
              </h3>
            </div>
            {hasQuestions ? (
              <ul className="space-y-2">
                {working!.unresolved_questions.map((q, i) => (
                  <li key={i} className="text-sm leading-relaxed flex items-start gap-2">
                    <span className="text-orange-400 mt-0.5">?</span>
                    <span>{q}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--text-secondary)] italic">No unresolved questions</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Deep Search Tab ──────────────────────────────────────────────────────────

function DeepSearchTab() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [topK, setTopK] = useState(20);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSearch() {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setSearched(true);
    try {
      const data = await api.searchMemory(q, topK);
      const rawResults = data.results || data.matches || [];
      setResults(rawResults);
    } catch (e) {
      console.error("Search failed:", e);
      setResults([]);
    }
    setLoading(false);
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Deep Search</h2>
        <p className="text-xs text-[var(--text-secondary)]">
          Search across all 6 memory tiers simultaneously. Returns results ranked by semantic similarity.
        </p>
      </div>

      {/* Search bar */}
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search across all memory tiers..."
            className="w-full px-4 py-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-sm focus:border-[var(--accent)] transition-colors"
          />
          {query && (
            <button
              onClick={() => { setQuery(""); setResults([]); setSearched(false); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-sm"
            >
              x
            </button>
          )}
        </div>
        <select
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm w-20"
          title="Max results"
        >
          <option value={5}>5</option>
          <option value={10}>10</option>
          <option value={20}>20</option>
          <option value={50}>50</option>
        </select>
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className={`px-6 py-2 rounded-lg text-sm font-medium transition-colors ${
            loading || !query.trim()
              ? "bg-[var(--bg-secondary)] text-[var(--text-secondary)] cursor-not-allowed"
              : "bg-[var(--accent)] text-white hover:opacity-90"
          }`}
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      {/* Results */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <span className="text-[var(--text-secondary)] animate-pulse">
            Searching across all memory tiers...
          </span>
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
          <p className="text-[var(--text-secondary)] mb-2">No results found</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Try different keywords or broader search terms
          </p>
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            {results.length} result{results.length !== 1 ? "s" : ""} across memory tiers
          </p>
          <div className="space-y-2">
            {results.map((result, i) => (
              <SearchResultCard key={i} result={result} index={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Search Result Card ───────────────────────────────────────────────────────

function SearchResultCard({ result, index }: { result: SearchResult; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const confidence = result.confidence ?? result.score ?? 0;
  const tier = result.tier || "unknown";
  const colors = tierColor(tier);

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[var(--text-secondary)]">
            #{index + 1}
          </span>
          <span
            className={`text-[10px] font-semibold px-2 py-0.5 rounded ${colors.bg} ${colors.text}`}
          >
            {tier.toUpperCase()}
          </span>
          {result.source && (
            <span className="text-[10px] text-[var(--text-secondary)] font-mono truncate max-w-[200px]">
              {result.source}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {result.timestamp && (
            <span className="text-[10px] text-[var(--text-secondary)]">
              {timeAgo(result.timestamp)}
            </span>
          )}
          <span
            className={`text-xs font-mono font-bold ${
              confidence >= 0.8
                ? "text-green-400"
                : confidence >= 0.5
                  ? "text-yellow-400"
                  : "text-[var(--text-secondary)]"
            }`}
          >
            {formatConfidence(confidence)}
          </span>
        </div>
      </div>

      {/* Content */}
      <div
        className="text-sm leading-relaxed cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <p className="whitespace-pre-wrap">{result.content}</p>
        ) : (
          <p>{truncate(result.content, 300)}</p>
        )}
      </div>

      {/* Tags */}
      {result.tags && result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {result.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-secondary)]"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Expand hint */}
      {result.content && result.content.length > 300 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] mt-2 transition-colors"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

// ─── Tier Explorer Tab ────────────────────────────────────────────────────────

function TierExplorerTab({ getTierCount }: { getTierCount: (id: string) => number }) {
  const [activeTier, setActiveTier] = useState<string>("working");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  // Reset search when switching tiers
  useEffect(() => {
    setSearchQuery("");
    setSearchResults([]);
    setSearched(false);
  }, [activeTier]);

  async function handleTierSearch() {
    const q = searchQuery.trim();
    if (!q) return;
    setSearching(true);
    setSearched(true);
    try {
      // Use the appropriate search based on tier
      let data;
      if (activeTier === "resource") {
        data = await api.search(q, "resources", 20);
      } else if (activeTier === "episodic") {
        data = await api.search(q, "episodic", 20);
      } else if (activeTier === "vault") {
        data = await api.search(q, "knowledge_vault", 20);
      } else {
        // For tiers without dedicated collection search, use cross-tier and filter
        data = await api.searchMemory(q, 30);
      }

      const rawResults: SearchResult[] = data.results || data.matches || data.documents || [];
      // Filter to the selected tier if we used cross-tier search
      const filtered = (activeTier === "resource" || activeTier === "episodic" || activeTier === "vault")
        ? rawResults
        : rawResults.filter((r: SearchResult) =>
            !r.tier || r.tier.toLowerCase() === activeTier.toLowerCase()
          );
      setSearchResults(filtered);
    } catch (e) {
      console.error("Tier search failed:", e);
      setSearchResults([]);
    }
    setSearching(false);
  }

  const tier = TIERS.find((t) => t.id === activeTier)!;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Tier Explorer</h2>
        <p className="text-xs text-[var(--text-secondary)]">
          Browse and search within individual memory tiers
        </p>
      </div>

      {/* Tier tabs */}
      <div className="flex flex-wrap gap-2">
        {TIERS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTier(t.id)}
            className={`px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTier === t.id
                ? `${t.colorBg} ${t.color} border border-current`
                : "border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--text-secondary)]"
            }`}
          >
            {t.name}
            <span className="ml-1.5 font-mono text-xs opacity-70">
              {getTierCount(t.id).toLocaleString()}
            </span>
          </button>
        ))}
      </div>

      {/* Selected tier info */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h3 className={`text-lg font-semibold ${tier.color}`}>{tier.name}</h3>
            <span className={`text-xs font-mono px-2 py-0.5 rounded ${tier.colorBg} ${tier.color}`}>
              {tier.backend}
            </span>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold font-mono">{getTierCount(tier.id).toLocaleString()}</p>
            <p className="text-[10px] text-[var(--text-secondary)]">entries</p>
          </div>
        </div>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {tier.description}
        </p>
      </div>

      {/* Tier-specific search */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
        <h3 className="text-sm font-semibold mb-3">
          Search {tier.name} Memory
        </h3>
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleTierSearch()}
            placeholder={`Search within ${tier.name.toLowerCase()} tier...`}
            className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm focus:border-[var(--accent)] transition-colors"
          />
          <button
            onClick={handleTierSearch}
            disabled={searching || !searchQuery.trim()}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              searching || !searchQuery.trim()
                ? "bg-[var(--bg-primary)] text-[var(--text-secondary)] cursor-not-allowed"
                : "bg-[var(--accent)] text-white hover:opacity-90"
            }`}
          >
            {searching ? "..." : "Search"}
          </button>
        </div>

        {/* Tier-specific details */}
        <TierDetails tierId={activeTier} />

        {/* Search results */}
        {searching && (
          <div className="flex items-center justify-center py-8">
            <span className="text-[var(--text-secondary)] animate-pulse">
              Searching {tier.name.toLowerCase()} tier...
            </span>
          </div>
        )}

        {!searching && searched && searchResults.length === 0 && (
          <div className="text-center py-6">
            <p className="text-sm text-[var(--text-secondary)]">
              No results in {tier.name.toLowerCase()} tier
            </p>
          </div>
        )}

        {!searching && searchResults.length > 0 && (
          <div className="space-y-2 mt-4">
            <p className="text-xs text-[var(--text-secondary)]">
              {searchResults.length} result{searchResults.length !== 1 ? "s" : ""}
            </p>
            {searchResults.map((result, i) => (
              <SearchResultCard key={i} result={{ ...result, tier: activeTier }} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tier Details ─────────────────────────────────────────────────────────────

function TierDetails({ tierId }: { tierId: string }) {
  const details: Record<string, { items: { label: string; value: string }[] }> = {
    working: {
      items: [
        { label: "Backend", value: "Redis (ephemeral key-value)" },
        { label: "Persistence", value: "None - cleared between sessions" },
        { label: "Refresh rate", value: "Real-time" },
        { label: "Fields", value: "active_task, active_priorities, unresolved_questions" },
      ],
    },
    episodic: {
      items: [
        { label: "Backend", value: "Qdrant collection: episodic" },
        { label: "Embedding", value: "Qwen3-Embedding (DEV:8001)" },
        { label: "Consolidation", value: "Daily 3:00 AM -> Vault" },
        { label: "Fields", value: "content, timestamp, session_id, source, tags" },
      ],
    },
    semantic: {
      items: [
        { label: "Backend", value: "Neo4j graph database (VAULT:7687)" },
        { label: "Node types", value: "Entity, Concept, Fact, Relation" },
        { label: "Total nodes", value: "3,241" },
        { label: "Query", value: "Cypher traversal + vector similarity" },
      ],
    },
    procedural: {
      items: [
        { label: "Backend", value: "PostgreSQL (VAULT)" },
        { label: "Total procedures", value: "10 operational recipes" },
        { label: "Categories", value: "Deploy, restart, troubleshoot, health-check" },
        { label: "Seed date", value: "2026-03-06" },
      ],
    },
    resource: {
      items: [
        { label: "Vector backend", value: "Qdrant collection: resources" },
        { label: "Full-text backend", value: "Meilisearch (VAULT:7700)" },
        { label: "Search mode", value: "Hybrid (vector + BM25)" },
        { label: "Ingested", value: "7 docs (95 chunks) + 15 codebase (235 chunks)" },
      ],
    },
    vault: {
      items: [
        { label: "Backends", value: "PostgreSQL + Qdrant (knowledge_vault)" },
        { label: "Purpose", value: "Long-term consolidated archive" },
        { label: "Source", value: "Working -> Episodic -> Vault pipeline" },
        { label: "Backup", value: "PG daily, Qdrant weekly (30-day retention)" },
      ],
    },
  };

  const tierDetails = details[tierId];
  if (!tierDetails) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 py-3 border-t border-[var(--border)]">
      {tierDetails.items.map((item) => (
        <div key={item.label}>
          <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider mb-0.5">
            {item.label}
          </p>
          <p className="text-xs font-mono">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

// ─── Store Tab ────────────────────────────────────────────────────────────────

function StoreTab() {
  const [content, setContent] = useState("");
  const [tier, setTier] = useState("episodic");
  const [source, setSource] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ type: "success" | "error"; message: string } | null>(null);

  async function handleStore() {
    if (!content.trim()) return;
    setSubmitting(true);
    setResult(null);

    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      const resp = await storeMemory({
        content: content.trim(),
        tier,
        source: source.trim() || undefined,
        tags: tags.length > 0 ? tags : undefined,
      });

      if (resp.error || resp.detail) {
        setResult({ type: "error", message: resp.error || resp.detail || "Unknown error" });
      } else {
        setResult({
          type: "success",
          message: `Memory stored successfully${resp.id ? ` (ID: ${resp.id})` : ""}`,
        });
        setContent("");
        setSource("");
        setTagsInput("");
      }
    } catch (e) {
      setResult({ type: "error", message: String(e) });
    }
    setSubmitting(false);
  }

  // Character count for content
  const charCount = content.length;
  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-semibold mb-1">Store Memory</h2>
        <p className="text-xs text-[var(--text-secondary)]">
          Manually store a memory entry into any tier. Entries are embedded and indexed automatically.
        </p>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-4">
        {/* Tier selector */}
        <div>
          <label className="text-sm font-medium mb-1.5 block">Target Tier</label>
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
          >
            {TIERS.filter((t) => t.id !== "working").map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.backend})
              </option>
            ))}
          </select>
          <p className="text-[10px] text-[var(--text-secondary)] mt-1">
            {TIERS.find((t) => t.id === tier)?.description}
          </p>
        </div>

        {/* Content */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-sm font-medium">Content</label>
            <span className="text-[10px] text-[var(--text-secondary)] font-mono">
              {charCount} chars / {wordCount} words
            </span>
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter the memory content to store..."
            rows={6}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm resize-y font-mono leading-relaxed"
          />
        </div>

        {/* Source */}
        <div>
          <label className="text-sm font-medium mb-1.5 block">
            Source
            <span className="text-[var(--text-secondary)] font-normal ml-1">(optional)</span>
          </label>
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g., manual, session-2026-03-06, documentation"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
          />
        </div>

        {/* Tags */}
        <div>
          <label className="text-sm font-medium mb-1.5 block">
            Tags
            <span className="text-[var(--text-secondary)] font-normal ml-1">(comma-separated, optional)</span>
          </label>
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="e.g., infrastructure, deployment, gpu"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
          />
          {tagsInput && (
            <div className="flex flex-wrap gap-1 mt-2">
              {tagsInput.split(",").map((t) => t.trim()).filter(Boolean).map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-primary)] border border-[var(--border)] text-[var(--text-secondary)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Preview card */}
        {content.trim() && (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-primary)] p-3">
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] mb-2">
              Preview
            </p>
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                  tierColor(tier).bg
                } ${tierColor(tier).text}`}
              >
                {tier.toUpperCase()}
              </span>
              {source && (
                <span className="text-[10px] text-[var(--text-secondary)] font-mono">
                  {source}
                </span>
              )}
            </div>
            <p className="text-xs leading-relaxed">{truncate(content, 200)}</p>
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]">
          <div>
            {result && (
              <p
                className={`text-xs ${
                  result.type === "success" ? "text-green-400" : "text-[var(--error)]"
                }`}
              >
                {result.message}
              </p>
            )}
          </div>
          <button
            onClick={handleStore}
            disabled={!content.trim() || submitting}
            className={`px-6 py-2 rounded-lg text-sm font-medium transition-colors ${
              content.trim() && !submitting
                ? "bg-[var(--accent)] text-white hover:opacity-90"
                : "bg-[var(--bg-primary)] text-[var(--text-secondary)] cursor-not-allowed"
            }`}
          >
            {submitting ? "Storing..." : "Store Memory"}
          </button>
        </div>
      </div>

      {/* Usage tips */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
        <h3 className="text-sm font-semibold mb-3">Storage Tips</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-[var(--text-secondary)]">
          <div className="space-y-2">
            <p>
              <span className="text-purple-400 font-semibold">Episodic</span> — Use for session logs, events,
              and decisions with timestamps. These consolidate to Vault daily.
            </p>
            <p>
              <span className="text-green-400 font-semibold">Semantic</span> — Use for facts, entity
              relationships, and structured knowledge about your system.
            </p>
          </div>
          <div className="space-y-2">
            <p>
              <span className="text-orange-400 font-semibold">Procedural</span> — Use for step-by-step
              instructions, runbooks, and operational procedures.
            </p>
            <p>
              <span className="text-yellow-400 font-semibold">Vault</span> — Use for important long-term
              knowledge that should never be forgotten.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
