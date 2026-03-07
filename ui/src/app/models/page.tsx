"use client";

import { useEffect, useState, useCallback } from "react";
import {
  api,
  type ModelDetail,
  type ModelsInfoResponse,
  type ClusterHealth,
} from "@/lib/api";

// ─── Constants ───────────────────────────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  hosted_vllm: "vLLM",
  anthropic: "Anthropic",
  openai: "OpenAI",
  deepseek: "DeepSeek",
  gemini: "Google",
  azure: "Azure",
};

const MODE_LABELS: Record<string, string> = {
  chat: "Chat",
  embedding: "Embedding",
  reranker: "Reranker",
};

// Known GPU assignments from the infrastructure layout
const GPU_ASSIGNMENTS: Record<string, string> = {
  reasoning: "GPU 0+1 (RTX 5070 Ti x2, TP=2)",
  coding: "GPU 2 (RTX 4090)",
  creative: "GPU 3 (RTX 5070 Ti)",
  fast: "GPU 0 (RTX 5090)",
  embedding: "GPU 0 (RTX 5060 Ti)",
  reranker: "GPU 0 (RTX 5060 Ti)",
};

// ─── Helpers ─────────────────────────────────────────────────────────────

function timeSince(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function statusColor(status: string): string {
  switch (status) {
    case "online":
      return "var(--success)";
    case "offline":
      return "var(--error)";
    case "degraded":
      return "var(--warning)";
    case "no_key":
      return "var(--warning)";
    default:
      return "var(--text-secondary)";
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "online":
      return "Online";
    case "offline":
      return "Offline";
    case "degraded":
      return "Degraded";
    case "no_key":
      return "No API Key";
    default:
      return "Unknown";
  }
}

function cleanModelName(name: string): string {
  // Remove leading path separators from hosted_vllm models
  // e.g. "/models/Qwen3-32B-AWQ" -> "Qwen3-32B-AWQ"
  return name.replace(/^\/models\//, "").replace(/^\/+/, "");
}

function providerBadgeStyle(provider: string): { bg: string; text: string } {
  switch (provider) {
    case "hosted_vllm":
      return { bg: "rgba(99, 179, 237, 0.15)", text: "rgb(99, 179, 237)" };
    case "anthropic":
      return { bg: "rgba(217, 149, 99, 0.15)", text: "rgb(217, 149, 99)" };
    case "openai":
      return { bg: "rgba(116, 185, 132, 0.15)", text: "rgb(116, 185, 132)" };
    case "deepseek":
      return { bg: "rgba(147, 130, 220, 0.15)", text: "rgb(147, 130, 220)" };
    case "gemini":
      return { bg: "rgba(66, 133, 244, 0.15)", text: "rgb(66, 133, 244)" };
    default:
      return { bg: "rgba(160, 160, 160, 0.15)", text: "rgb(160, 160, 160)" };
  }
}

// ─── Model Card Component ────────────────────────────────────────────────

function ModelCard({ model }: { model: ModelDetail }) {
  const displayName = cleanModelName(model.model_name);
  const providerLabel = PROVIDER_LABELS[model.provider] || model.provider;
  const modeLabel = MODE_LABELS[model.mode || "chat"] || model.mode || "Chat";
  const badge = providerBadgeStyle(model.provider);
  const gpuInfo = model.is_local ? GPU_ASSIGNMENTS[model.alias] : null;

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-3">
      {/* Header: alias + status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ background: statusColor(model.status) }}
          />
          <h3 className="font-semibold text-lg leading-none capitalize">
            {model.alias}
          </h3>
        </div>
        <span
          className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{
            background: statusColor(model.status),
            color: "var(--bg-primary)",
            opacity: model.status === "unknown" ? 0.5 : 1,
          }}
        >
          {statusLabel(model.status)}
        </span>
      </div>

      {/* Model path */}
      <div className="text-sm font-mono text-[var(--text-secondary)] truncate" title={displayName}>
        {displayName}
      </div>

      {/* Metadata grid */}
      <div className="space-y-2 text-sm">
        {/* Provider badge */}
        <div className="flex items-center justify-between">
          <span className="text-[var(--text-secondary)]">Provider</span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-md"
            style={{ background: badge.bg, color: badge.text }}
          >
            {providerLabel}
          </span>
        </div>

        {/* Mode */}
        <div className="flex items-center justify-between">
          <span className="text-[var(--text-secondary)]">Mode</span>
          <span className="text-xs font-mono text-[var(--text-primary)]">
            {modeLabel}
          </span>
        </div>

        {/* Node */}
        {model.node && (
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Node</span>
            <span className="text-xs font-mono font-semibold text-[var(--text-primary)]">
              {model.node}
            </span>
          </div>
        )}

        {/* Cloud indicator */}
        {!model.is_local && (
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Type</span>
            <span className="text-xs font-mono text-[var(--text-secondary)]">
              Cloud API
            </span>
          </div>
        )}

        {/* GPU assignment for local models */}
        {gpuInfo && (
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">GPU</span>
            <span className="text-xs font-mono text-[var(--text-primary)]">
              {gpuInfo}
            </span>
          </div>
        )}

        {/* API base for local models */}
        {model.api_base && (
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Endpoint</span>
            <span
              className="text-xs font-mono text-[var(--text-secondary)] truncate ml-2"
              title={model.api_base}
            >
              {model.api_base}
            </span>
          </div>
        )}
      </div>

      {/* No API key warning for cloud models */}
      {model.status === "no_key" && (
        <div className="text-xs text-[var(--warning)] border border-[var(--warning)]/20 bg-[var(--warning)]/5 rounded-md px-3 py-2">
          API key not configured on VAULT
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────

export default function ModelsPage() {
  const [modelsData, setModelsData] = useState<ModelsInfoResponse | null>(null);
  const [clusterHealth, setClusterHealth] = useState<ClusterHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [, setTick] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const [modelsResp, healthResp] = await Promise.allSettled([
        api.getModelInfo(),
        api.clusterHealth(),
      ]);

      if (modelsResp.status === "fulfilled") {
        setModelsData(modelsResp.value);
        setLastUpdated(new Date().toISOString());
        setError(null);
      } else {
        setError("Failed to fetch model info");
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

  // ─── Derived stats ─────────────────────────────────────────────────────

  const models = modelsData?.models || [];
  const localModels = models.filter((m) => m.is_local);
  const cloudModels = models.filter((m) => !m.is_local);
  const onlineCount = models.filter((m) => m.status === "online").length;
  const totalCount = models.length;

  // Count unique active inference endpoints (local only, by api_base)
  const activeEndpoints = new Set(
    localModels.filter((m) => m.status === "online" && m.api_base).map((m) => m.api_base)
  ).size;

  // LiteLLM status from cluster health
  const litellmHealth = clusterHealth?.litellm as Record<string, unknown> | undefined;
  const litellmStatus = litellmHealth
    ? (litellmHealth.status as string) || "unknown"
    : "unknown";

  const litellmStatusColor =
    litellmStatus === "ok"
      ? "var(--success)"
      : litellmStatus === "degraded"
        ? "var(--warning)"
        : litellmStatus === "unreachable"
          ? "var(--error)"
          : "var(--text-secondary)";

  const litellmStatusLabel =
    litellmStatus === "ok"
      ? "Healthy"
      : litellmStatus === "degraded"
        ? "Degraded"
        : litellmStatus === "unreachable"
          ? "Unreachable"
          : "Unknown";

  // ─── Render ────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Models</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            LLM model aliases routed through LiteLLM to vLLM and cloud APIs
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
      {loading && !modelsData && (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-3">
            <div className="relative w-10 h-10">
              <div className="absolute inset-0 border-2 border-[var(--border)] rounded-full" />
              <div className="absolute inset-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            </div>
            <span className="text-sm text-[var(--text-secondary)]">
              Loading model info...
            </span>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && !modelsData && (
        <div className="rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-6 text-center">
          <p className="text-[var(--error)] mb-2">{error}</p>
          <p className="text-sm text-[var(--text-secondary)]">
            Check that the gateway is running and LiteLLM is accessible.
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
      {modelsData && (
        <>
          {/* Overview Strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            {/* Total Models */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                Models
              </span>
              <div className="text-2xl font-bold font-mono">
                {onlineCount}
                <span className="text-sm text-[var(--text-secondary)] font-normal">
                  {" "}/ {totalCount}
                </span>
              </div>
              <span className="text-xs text-[var(--text-secondary)]">
                online
              </span>
            </div>

            {/* Local vs Cloud */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                Distribution
              </span>
              <div className="text-2xl font-bold font-mono">
                {localModels.length}
                <span className="text-sm text-[var(--text-secondary)] font-normal">
                  {" "}local
                </span>
              </div>
              <span className="text-xs text-[var(--text-secondary)]">
                {cloudModels.length} cloud
              </span>
            </div>

            {/* Active Endpoints */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider block mb-1">
                Endpoints
              </span>
              <div className="text-2xl font-bold font-mono">
                {activeEndpoints}
              </div>
              <span className="text-xs text-[var(--text-secondary)]">
                active vLLM instances
              </span>
            </div>

            {/* LiteLLM Status */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: litellmStatusColor }}
                />
                <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider">
                  LiteLLM
                </span>
              </div>
              <div className="text-2xl font-bold font-mono" style={{ color: litellmStatusColor }}>
                {litellmStatusLabel}
              </div>
              <span className="text-xs text-[var(--text-secondary)]">
                VAULT:4000
              </span>
            </div>
          </div>

          {/* Empty State */}
          {models.length === 0 && (
            <div className="text-center py-12 text-[var(--text-secondary)]">
              <p className="text-lg mb-2">No models found</p>
              <p className="text-sm">
                LiteLLM may not be returning model information. Check the proxy
                config at VAULT:4000.
              </p>
            </div>
          )}

          {/* Local Models Section */}
          {localModels.length > 0 && (
            <div className="mb-8">
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-lg font-semibold">Local Models</h2>
                <span className="text-xs px-2 py-0.5 rounded-full bg-[rgba(99,179,237,0.15)] text-[rgb(99,179,237)]">
                  {localModels.length}
                </span>
              </div>
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                {localModels.map((model) => (
                  <ModelCard key={model.alias} model={model} />
                ))}
              </div>
            </div>
          )}

          {/* Cloud Models Section */}
          {cloudModels.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-lg font-semibold">Cloud Models</h2>
                <span className="text-xs px-2 py-0.5 rounded-full bg-[rgba(160,160,160,0.15)] text-[rgb(160,160,160)]">
                  {cloudModels.length}
                </span>
              </div>
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                {cloudModels.map((model) => (
                  <ModelCard key={model.alias} model={model} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
