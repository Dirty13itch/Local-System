"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  api,
  type QueenProfile,
  type QueenDNA,
  type DropEntry,
  type DropDetail,
} from "@/lib/api";
import { ImageUpload } from "@/components/ImageUpload";
import { ImageGallery } from "@/components/ImageGallery";
import { GeneratingSpinner } from "@/components/ProgressBar";
import { QueenCard } from "@/components/QueenCard";
import { DNARadar } from "@/components/DNARadar";

// ─── Types ───────────────────────────────────────────────────────────────────

type Tab = "create" | "face" | "queens" | "train" | "drops";

interface GeneratedImage {
  src: string;
  prompt?: string;
  timestamp?: string;
}

interface Pipeline {
  id: string;
  name: string;
  type: string;
  est_time: string;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "drops", label: "Drops", icon: "📂" },
  { id: "create", label: "Create", icon: "✦" },
  { id: "face", label: "Face Gen", icon: "◉" },
  { id: "queens", label: "Queens", icon: "♛" },
  { id: "train", label: "Train", icon: "⚙" },
];

const DEFAULT_NEGATIVE = "blurry, low quality, deformed, ugly, bad anatomy, disfigured, poorly drawn, extra limbs";

// ─── Page ────────────────────────────────────────────────────────────────────

export default function GeneratePage() {
  const [activeTab, setActiveTab] = useState<Tab>("drops");

  return (
    <div className="h-full flex flex-col">
      {/* Header with tabs */}
      <div className="border-b border-[var(--border)] bg-[var(--bg-secondary)]">
        <div className="flex items-center justify-between px-6 pt-4 pb-0">
          <h1 className="text-xl font-bold">Generation Studio</h1>
          <StatusBadge />
        </div>
        <div className="flex gap-1 px-6 mt-3">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                px-4 py-2 text-sm rounded-t-lg transition-colors border-b-2
                ${
                  activeTab === tab.id
                    ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--bg-primary)]"
                    : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"
                }
              `}
            >
              <span className="mr-1.5">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "drops" && <DropsTab />}
        {activeTab === "create" && <CreateTab />}
        {activeTab === "face" && <FaceGenTab />}
        {activeTab === "queens" && <QueensTab />}
        {activeTab === "train" && <TrainTab />}
      </div>
    </div>
  );
}

// ─── Status Badge ────────────────────────────────────────────────────────────

function StatusBadge() {
  const [status, setStatus] = useState<{ active_service: string; queue_running: number; queue_pending: number } | null>(null);

  useEffect(() => {
    const poll = () => api.generationStatus().then(setStatus);
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  if (!status) return null;

  const isOnline = status.active_service !== "offline";
  return (
    <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)]">
      {status.queue_running > 0 && (
        <span className="text-[var(--warning)]">
          {status.queue_running} running · {status.queue_pending} queued
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${isOnline ? "bg-green-500" : "bg-red-500"}`} />
        {status.active_service}
      </span>
    </div>
  );
}

// ─── Tab 0: Drops ───────────────────────────────────────────────────────────

function DropsTab() {
  const [drops, setDrops] = useState<DropEntry[]>([]);
  const [scannerRunning, setScannerRunning] = useState(false);
  const [selectedDrop, setSelectedDrop] = useState<string | null>(null);
  const [detail, setDetail] = useState<DropDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load drops list
  const loadDrops = useCallback(async () => {
    try {
      const status = await api.listDrops();
      setDrops(status.entries);
      setScannerRunning(status.scanner_running);
    } catch {
      // Offline
    }
  }, []);

  useEffect(() => {
    loadDrops().then(() => setLoading(false));
    pollRef.current = setInterval(loadDrops, 8000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadDrops]);

  // Load detail when selected
  useEffect(() => {
    if (!selectedDrop) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      const d = await api.getDropDetail(selectedDrop);
      if (!cancelled) setDetail(d);
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selectedDrop]);

  const triggerScan = async () => {
    setScanning(true);
    try {
      await api.scanDrops();
      await loadDrops();
    } finally {
      setScanning(false);
    }
  };

  const triggerProcess = async (name: string) => {
    await api.processDrop(name);
    await loadDrops();
  };

  const triggerRetry = async (name: string) => {
    await api.retryDrop(name);
    await loadDrops();
  };

  const statusColor = (s: string) => {
    switch (s) {
      case "done":
        return "bg-green-500/20 text-green-400";
      case "processing":
        return "bg-blue-500/20 text-blue-400";
      case "error":
        return "bg-red-500/20 text-red-400";
      default:
        return "bg-yellow-500/20 text-yellow-400";
    }
  };

  const formatTime = (ts: number) => {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <div className="p-6 text-[var(--text-secondary)]">Loading drops...</div>
    );
  }

  return (
    <div className="p-6">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold">Drop Folder</h2>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            Drop a folder of photos into{" "}
            <code className="bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded text-[10px]">
              \\VAULT\data\gen-drops\
            </code>{" "}
            — auto-generates portraits from face references
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <span
              className={`w-2 h-2 rounded-full ${scannerRunning ? "bg-green-500 animate-pulse" : "bg-red-500"}`}
            />
            Scanner {scannerRunning ? "active" : "off"}
          </span>
          <button
            onClick={triggerScan}
            disabled={scanning}
            className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-40 transition-colors"
          >
            {scanning ? "Scanning..." : "Scan Now"}
          </button>
        </div>
      </div>

      {drops.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <div className="text-4xl mb-3">📂</div>
          <p className="text-sm mb-1">No drops yet</p>
          <p className="text-xs">
            Create a folder with photos inside{" "}
            <code className="bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded">
              \\VAULT\data\gen-drops\
            </code>
          </p>
          <p className="text-xs mt-2 text-[var(--text-secondary)]">
            Example: <code className="bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded">gen-drops\jane-doe\</code> with 3-10 face photos
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_400px] gap-6">
          {/* Drops list */}
          <div className="space-y-2">
            {drops.map((drop) => (
              <button
                key={drop.name}
                onClick={() =>
                  setSelectedDrop(
                    selectedDrop === drop.name ? null : drop.name,
                  )
                }
                className={`
                  w-full text-left rounded-lg border p-3 transition-all
                  ${
                    selectedDrop === drop.name
                      ? "border-[var(--accent)] bg-[var(--accent)]/5 ring-1 ring-[var(--accent)]/20"
                      : "border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--text-secondary)]"
                  }
                `}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-lg">
                      {drop.status === "done"
                        ? "✅"
                        : drop.status === "processing"
                          ? "⚡"
                          : drop.status === "error"
                            ? "❌"
                            : "⏳"}
                    </span>
                    <div className="min-w-0">
                      <h3 className="text-sm font-medium truncate">
                        {drop.name}
                      </h3>
                      <p className="text-xs text-[var(--text-secondary)]">
                        {drop.image_count} source image
                        {drop.image_count !== 1 ? "s" : ""} ·{" "}
                        {formatTime(drop.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {drop.status === "done" && (
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        {drop.images_generated} generated
                      </span>
                    )}
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${statusColor(drop.status)}`}
                    >
                      {drop.status}
                    </span>
                    {drop.status === "pending" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          triggerProcess(drop.name);
                        }}
                        className="text-[10px] px-2 py-0.5 rounded bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
                      >
                        Process
                      </button>
                    )}
                    {drop.status === "error" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          triggerRetry(drop.name);
                        }}
                        className="text-[10px] px-2 py-0.5 rounded bg-[var(--warning)] text-black hover:opacity-80 transition-colors"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </div>
                {drop.error && (
                  <p className="text-[10px] text-red-400 mt-1.5 truncate">
                    {drop.error}
                  </p>
                )}
              </button>
            ))}
          </div>

          {/* Detail panel */}
          {selectedDrop && detail && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4 space-y-4 self-start sticky top-4">
              <div>
                <h3 className="font-semibold text-sm">{detail.name}</h3>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                  Status: <span className={`px-1.5 py-0.5 rounded ${statusColor(detail.status)}`}>{detail.status}</span>
                </p>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
                  <p className="text-lg font-bold">{detail.image_count}</p>
                  <p className="text-[10px] text-[var(--text-secondary)]">Sources</p>
                </div>
                <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
                  <p className="text-lg font-bold">{detail.refs_created}</p>
                  <p className="text-[10px] text-[var(--text-secondary)]">Refs</p>
                </div>
                <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
                  <p className="text-lg font-bold">{detail.images_generated}</p>
                  <p className="text-[10px] text-[var(--text-secondary)]">Generated</p>
                </div>
              </div>

              {/* Manifest info */}
              {detail.manifest && (
                <div className="text-xs space-y-1.5">
                  <p className="font-medium text-[var(--text-secondary)] uppercase tracking-wider text-[10px]">
                    Processing Details
                  </p>
                  <p>
                    <span className="text-[var(--text-secondary)]">Pipeline:</span>{" "}
                    {detail.manifest.pipeline}
                  </p>
                  <p>
                    <span className="text-[var(--text-secondary)]">Identity:</span>{" "}
                    {detail.manifest.identity_method}
                  </p>
                  <p>
                    <span className="text-[var(--text-secondary)]">Processed:</span>{" "}
                    {detail.manifest.processed_at}
                  </p>
                  <div>
                    <span className="text-[var(--text-secondary)]">Prompt:</span>
                    <p className="mt-1 bg-[var(--bg-primary)] rounded p-2 text-[10px] leading-relaxed max-h-20 overflow-auto">
                      {detail.manifest.prompt_used}
                    </p>
                  </div>
                </div>
              )}

              {/* Reference images */}
              {detail.manifest && detail.manifest.ref_images.length > 0 && (
                <div>
                  <p className="text-[10px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    References
                  </p>
                  <div className="grid grid-cols-4 gap-1.5">
                    {detail.manifest.ref_images.map((ref) => (
                      <div
                        key={ref}
                        className="aspect-square rounded-lg overflow-hidden border border-[var(--border)]"
                      >
                        <img
                          src={api.getDropRefUrl(detail.name, ref)}
                          alt={ref}
                          className="w-full h-full object-cover"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Generated images */}
              {detail.output_images && detail.output_images.length > 0 && (
                <div>
                  <p className="text-[10px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                    Generated
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {detail.output_images.map((img) => (
                      <div
                        key={img}
                        className="aspect-[3/4] rounded-lg overflow-hidden border border-[var(--border)] cursor-pointer hover:border-[var(--accent)] transition-colors"
                      >
                        <img
                          src={api.getDropImageUrl(detail.name, img)}
                          alt={img}
                          className="w-full h-full object-cover"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Also show generated images from manifest if output_images not set */}
              {!detail.output_images &&
                detail.manifest &&
                detail.manifest.generated_images.length > 0 && (
                  <div>
                    <p className="text-[10px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                      Generated
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                      {detail.manifest.generated_images.map((img) => (
                        <div
                          key={img}
                          className="aspect-[3/4] rounded-lg overflow-hidden border border-[var(--border)] cursor-pointer hover:border-[var(--accent)] transition-colors"
                        >
                          <img
                            src={api.getDropImageUrl(detail.name, img)}
                            alt={img}
                            className="w-full h-full object-cover"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Tab 1: Create ───────────────────────────────────────────────────────────

function CreateTab() {
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState(DEFAULT_NEGATIVE);
  const [pipeline, setPipeline] = useState("flux-uncensored");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [steps, setSteps] = useState(25);
  const [cfg, setCfg] = useState(3.5);
  const [seed, setSeed] = useState(-1);
  const [loraName, setLoraName] = useState("");
  const [loraStrength, setLoraStrength] = useState(1.0);
  const [showSettings, setShowSettings] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loras, setLoras] = useState<string[]>([]);

  useEffect(() => {
    api.listPipelines().then(setPipelines);
    api.listGenModels().then((m) => setLoras(m.loras || []));
  }, []);

  const generate = async () => {
    if (!prompt.trim() || generating) return;
    setGenerating(true);
    try {
      const resp = await api.generateImage({
        prompt: prompt.trim(),
        negative_prompt: negative,
        pipeline,
        width,
        height,
        steps,
        cfg,
        seed,
        lora_name: loraName || undefined,
        lora_strength: loraName ? loraStrength : undefined,
      });

      // Poll for completion (simple approach — check history)
      await pollForResult(resp.prompt_id, prompt.trim());
    } catch (err) {
      console.error("Generation failed:", err);
    } finally {
      setGenerating(false);
    }
  };

  const pollForResult = async (promptId: string, promptText: string) => {
    for (let i = 0; i < 120; i++) {
      await sleep(2000);
      try {
        const history = await api.generationHistory();
        const entry = (history as Record<string, Record<string, unknown>>)[promptId];
        if (entry && entry.outputs) {
          const outputs = entry.outputs as Record<string, { images?: Array<{ filename: string; type: string }> }>;
          for (const nodeId of Object.keys(outputs)) {
            const nodeOutput = outputs[nodeId];
            if (nodeOutput.images) {
              for (const img of nodeOutput.images) {
                setImages((prev) => [
                  { src: api.getImageUrl(img.filename, img.type), prompt: promptText, timestamp: new Date().toISOString() },
                  ...prev,
                ]);
              }
            }
          }
          return;
        }
      } catch {
        // Keep polling
      }
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Main area */}
        <div className="space-y-4">
          {/* Prompt */}
          <div>
            <label className="block text-sm font-medium mb-1.5">Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe what you want to generate..."
              className="w-full h-28 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm resize-none focus:outline-none focus:border-[var(--accent)]"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) generate();
              }}
            />
          </div>

          {/* Negative prompt */}
          <div>
            <label className="block text-sm font-medium mb-1.5">Negative Prompt</label>
            <textarea
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              className="w-full h-16 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-xs resize-none focus:outline-none focus:border-[var(--accent)] text-[var(--text-secondary)]"
            />
          </div>

          {/* Generate button */}
          <div className="flex items-center gap-3">
            <button
              onClick={generate}
              disabled={!prompt.trim() || generating}
              className="px-6 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {generating ? "Generating..." : "Generate"}
            </button>
            <span className="text-xs text-[var(--text-secondary)]">Ctrl+Enter</span>
          </div>

          {/* Progress */}
          {generating && <GeneratingSpinner />}

          {/* Gallery */}
          <div className="mt-6">
            <h3 className="text-sm font-medium mb-3">Results</h3>
            <ImageGallery images={images} columns={3} />
          </div>
        </div>

        {/* Sidebar settings */}
        <div className="space-y-4">
          {/* Pipeline */}
          <div>
            <label className="block text-xs font-medium mb-1.5 text-[var(--text-secondary)]">Pipeline</label>
            <select
              value={pipeline}
              onChange={(e) => setPipeline(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              {pipelines.length > 0 ? (
                pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.est_time})
                  </option>
                ))
              ) : (
                <>
                  <option value="flux-uncensored">FLUX Uncensored (~50s)</option>
                  <option value="realvis-xl">RealVis XL (~30s)</option>
                </>
              )}
            </select>
          </div>

          {/* Dimensions */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-[var(--text-secondary)] mb-1">Width</label>
              <input
                type="number"
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
                step={64}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--text-secondary)] mb-1">Height</label>
              <input
                type="number"
                value={height}
                onChange={(e) => setHeight(Number(e.target.value))}
                step={64}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>

          {/* Dimension presets */}
          <div className="flex flex-wrap gap-1.5">
            {[
              { label: "1:1", w: 1024, h: 1024 },
              { label: "Portrait", w: 832, h: 1216 },
              { label: "Landscape", w: 1344, h: 768 },
              { label: "Wide", w: 1536, h: 640 },
            ].map((preset) => (
              <button
                key={preset.label}
                onClick={() => {
                  setWidth(preset.w);
                  setHeight(preset.h);
                }}
                className={`text-xs px-2 py-1 rounded border transition-colors ${
                  width === preset.w && height === preset.h
                    ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10"
                    : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-secondary)]"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {/* Steps / CFG / Seed */}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            {showSettings ? "▾ Hide advanced" : "▸ Advanced settings"}
          </button>

          {showSettings && (
            <div className="space-y-3 pt-1">
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">
                  Steps ({steps})
                </label>
                <input
                  type="range"
                  min={1}
                  max={50}
                  value={steps}
                  onChange={(e) => setSteps(Number(e.target.value))}
                  className="w-full accent-[var(--accent)]"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">
                  CFG ({cfg.toFixed(1)})
                </label>
                <input
                  type="range"
                  min={1}
                  max={20}
                  step={0.5}
                  value={cfg}
                  onChange={(e) => setCfg(Number(e.target.value))}
                  className="w-full accent-[var(--accent)]"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">Seed (-1 = random)</label>
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              {/* LoRA */}
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1">LoRA</label>
                <select
                  value={loraName}
                  onChange={(e) => setLoraName(e.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="">None</option>
                  {loras.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              {loraName && (
                <div>
                  <label className="block text-xs text-[var(--text-secondary)] mb-1">
                    LoRA Strength ({loraStrength.toFixed(2)})
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={loraStrength}
                    onChange={(e) => setLoraStrength(Number(e.target.value))}
                    className="w-full accent-[var(--accent)]"
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Tab 2: Face Gen ─────────────────────────────────────────────────────────

function FaceGenTab() {
  const [refImage, setRefImage] = useState<string | null>(null);
  const [refFilename, setRefFilename] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [identityStrength, setIdentityStrength] = useState(1.0);
  const [generating, setGenerating] = useState(false);
  const [images, setImages] = useState<GeneratedImage[]>([]);

  const handleUpload = useCallback(async (file: File) => {
    const result = await api.uploadImage(file);
    setRefFilename(result.name);
    // Create local preview
    const reader = new FileReader();
    reader.onload = (e) => setRefImage(e.target?.result as string);
    reader.readAsDataURL(file);
  }, []);

  const generate = async () => {
    if (!refFilename || !prompt.trim() || generating) return;
    setGenerating(true);
    try {
      const resp = await api.generateFace({
        prompt: prompt.trim(),
        reference_image: refFilename,
        identity_strength: identityStrength,
      });

      // Poll for result
      for (let i = 0; i < 120; i++) {
        await sleep(2000);
        try {
          const history = await api.generationHistory();
          const entry = (history as Record<string, Record<string, unknown>>)[resp.prompt_id];
          if (entry && entry.outputs) {
            const outputs = entry.outputs as Record<string, { images?: Array<{ filename: string; type: string }> }>;
            for (const nodeId of Object.keys(outputs)) {
              const nodeOutput = outputs[nodeId];
              if (nodeOutput.images) {
                for (const img of nodeOutput.images) {
                  setImages((prev) => [
                    { src: api.getImageUrl(img.filename, img.type), prompt: prompt.trim() },
                    ...prev,
                  ]);
                }
              }
            }
            break;
          }
        } catch {
          // Keep polling
        }
      }
    } catch (err) {
      console.error("Face generation failed:", err);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left — upload + settings */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1.5">Reference Face</label>
            <ImageUpload
              onUpload={handleUpload}
              preview={refImage}
              label="Upload a reference face photo"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">Scene Description</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the scene, pose, outfit, setting..."
              className="w-full h-24 rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm resize-none focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              Identity Strength ({identityStrength.toFixed(2)})
            </label>
            <input
              type="range"
              min={0}
              max={1.5}
              step={0.05}
              value={identityStrength}
              onChange={(e) => setIdentityStrength(Number(e.target.value))}
              className="w-full accent-[var(--accent)]"
            />
            <p className="text-[10px] text-[var(--text-secondary)] mt-1">
              Higher = closer to reference face, lower = more creative freedom
            </p>
          </div>

          <button
            onClick={generate}
            disabled={!refFilename || !prompt.trim() || generating}
            className="px-6 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {generating ? "Generating..." : "Generate with Face"}
          </button>

          {generating && <GeneratingSpinner label="Preserving identity..." />}
        </div>

        {/* Right — results */}
        <div>
          <h3 className="text-sm font-medium mb-3">Results</h3>
          <ImageGallery images={images} columns={2} />
        </div>
      </div>
    </div>
  );
}

// ─── Tab 3: Queens ───────────────────────────────────────────────────────────

function QueensTab() {
  const [queens, setQueens] = useState<QueenProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"portrait" | "scene">("portrait");
  const [sceneIndex, setSceneIndex] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listQueens().then((q) => {
      setQueens(q);
      if (q.length > 0) setSelectedId(q[0].id);
    }).finally(() => setLoading(false));
  }, []);

  const selected = queens.find((q) => q.id === selectedId);

  const generate = async () => {
    if (!selectedId || generating) return;
    setGenerating(true);
    try {
      const resp = await api.generateQueen({
        queen_id: selectedId,
        mode,
        scene_index: mode === "scene" ? sceneIndex : undefined,
      });

      // Poll for result
      for (let i = 0; i < 120; i++) {
        await sleep(2000);
        try {
          const history = await api.generationHistory();
          const entry = (history as Record<string, Record<string, unknown>>)[resp.prompt_id];
          if (entry && entry.outputs) {
            const outputs = entry.outputs as Record<string, { images?: Array<{ filename: string; type: string }> }>;
            for (const nodeId of Object.keys(outputs)) {
              const nodeOutput = outputs[nodeId];
              if (nodeOutput.images) {
                for (const img of nodeOutput.images) {
                  setImages((prev) => [
                    { src: api.getImageUrl(img.filename, img.type), prompt: selected?.name },
                    ...prev,
                  ]);
                }
              }
            }
            break;
          }
        } catch {
          // Keep polling
        }
      }
    } catch (err) {
      console.error("Queen generation failed:", err);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 text-[var(--text-secondary)]">Loading queens...</div>
    );
  }

  if (queens.length === 0) {
    return (
      <div className="p-6 text-center py-12 text-[var(--text-secondary)]">
        <p className="text-lg mb-2">No queens loaded</p>
        <p className="text-sm">Configure the EoBQ Master Document path in the gateway.</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr_320px] gap-6">
        {/* Queen selector */}
        <div className="space-y-2 max-h-[calc(100vh-160px)] overflow-auto pr-1">
          <h3 className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
            Queens ({queens.length})
          </h3>
          {queens.map((q) => (
            <QueenCard
              key={q.id}
              queen={q}
              selected={q.id === selectedId}
              onClick={() => {
                setSelectedId(q.id);
                setSceneIndex(0);
              }}
            />
          ))}
        </div>

        {/* Center — details + generate */}
        {selected && (
          <div className="space-y-5">
            {/* Header */}
            <div>
              <h2 className="text-2xl font-bold">{selected.name}</h2>
              <p className="text-sm text-[var(--text-secondary)]">
                Inspired by {selected.performer_ref}
              </p>
            </div>

            {/* DNA Radar */}
            <div className="flex justify-center">
              <DNARadar dna={selected.dna} size={300} />
            </div>

            {/* Physical Blueprint */}
            {Object.keys(selected.physical_blueprint).length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                  Physical Blueprint
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.entries(selected.physical_blueprint).map(([k, v]) => (
                    <div key={k} className="text-xs">
                      <span className="text-[var(--text-secondary)] capitalize">{k.replace(/_/g, " ")}: </span>
                      <span>{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Flux prompt preview */}
            <div>
              <h3 className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-2">
                Flux Prompt
              </h3>
              <p className="text-xs text-[var(--text-secondary)] bg-[var(--bg-tertiary)] rounded-lg p-3 leading-relaxed max-h-24 overflow-auto">
                {mode === "scene" && selected.scenes[sceneIndex]
                  ? selected.scenes[sceneIndex].flux_prompt
                  : selected.flux_portrait_prompt || "No portrait prompt defined"}
              </p>
            </div>

            {/* Results */}
            <div>
              <h3 className="text-sm font-medium mb-3">Generated</h3>
              {generating && <GeneratingSpinner label={`Generating ${selected.name}...`} />}
              <ImageGallery images={images} columns={2} />
            </div>
          </div>
        )}

        {/* Right — generation controls */}
        {selected && (
          <div className="space-y-4">
            {/* Mode selector */}
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Mode</label>
              <div className="grid grid-cols-2 gap-2">
                {(["portrait", "scene"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={`
                      py-2 rounded-lg text-sm border transition-colors capitalize
                      ${
                        mode === m
                          ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10"
                          : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-secondary)]"
                      }
                    `}
                  >
                    {m}
                    <span className="block text-[10px] mt-0.5 opacity-70">
                      {m === "portrait" ? "832×1216" : "1344×768"}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Scene selector */}
            {mode === "scene" && selected.scenes.length > 0 && (
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Scene</label>
                <select
                  value={sceneIndex}
                  onChange={(e) => setSceneIndex(Number(e.target.value))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {selected.scenes.map((s, i) => (
                    <option key={i} value={i}>
                      {s.title}
                    </option>
                  ))}
                </select>
                {selected.scenes[sceneIndex] && (
                  <p className="text-[10px] text-[var(--text-secondary)] mt-1.5 leading-relaxed">
                    {selected.scenes[sceneIndex].description}
                  </p>
                )}
              </div>
            )}

            {/* Identity info */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs space-y-1.5">
              <p className="font-medium text-[var(--text-secondary)]">Identity Method</p>
              {selected.lora_name ? (
                <p className="text-green-400">✓ Custom LoRA: {selected.lora_name}</p>
              ) : selected.reference_images.length > 0 ? (
                <p className="text-blue-400">◉ PuLID with {selected.reference_images.length} reference(s)</p>
              ) : (
                <p className="text-[var(--warning)]">⚠ No identity — prompt only</p>
              )}
            </div>

            {/* Generate */}
            <button
              onClick={generate}
              disabled={generating}
              className="w-full px-6 py-3 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {generating ? "Generating..." : `Generate ${mode === "portrait" ? "Portrait" : "Scene"}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tab 4: Train ────────────────────────────────────────────────────────────

function TrainTab() {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [triggerWord, setTriggerWord] = useState("");
  const [modelType, setModelType] = useState<"sdxl" | "flux">("sdxl");
  const [preparing, setPreparing] = useState(false);
  const [training, setTraining] = useState(false);
  const [status, setStatus] = useState<string>("");

  const handleUpload = useCallback(async (file: File) => {
    setFiles((prev) => [...prev, file]);
    const reader = new FileReader();
    reader.onload = (e) => setPreviews((prev) => [...prev, e.target?.result as string]);
    reader.readAsDataURL(file);
  }, []);

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setPreviews((prev) => prev.filter((_, i) => i !== idx));
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Upload */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          Training Photos ({files.length}/30)
        </label>
        <ImageUpload
          onUpload={handleUpload}
          multiple
          label="Drop 15-30 photos of the subject"
        />
      </div>

      {/* Preview grid */}
      {previews.length > 0 && (
        <div className="grid grid-cols-6 sm:grid-cols-8 gap-2">
          {previews.map((src, i) => (
            <div key={i} className="relative aspect-square rounded-lg overflow-hidden border border-[var(--border)] group">
              <img src={src} alt={`Photo ${i + 1}`} className="w-full h-full object-cover" />
              <button
                onClick={() => removeFile(i)}
                className="absolute top-1 right-1 w-5 h-5 rounded-full bg-red-500/80 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Settings */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            Trigger Word
          </label>
          <input
            type="text"
            value={triggerWord}
            onChange={(e) => setTriggerWord(e.target.value)}
            placeholder="e.g. janedoe"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)]"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            Base Model
          </label>
          <select
            value={modelType}
            onChange={(e) => setModelType(e.target.value as "sdxl" | "flux")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="sdxl">SDXL (faster, good quality)</option>
            <option value="flux">FLUX (slower, best quality)</option>
          </select>
        </div>
        <div className="flex items-end">
          <button
            disabled={files.length < 5 || !triggerWord.trim() || preparing || training}
            className="w-full px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            onClick={() => {
              setPreparing(true);
              setStatus("Preparing dataset: cropping faces, generating captions...");
              // In a real implementation, this would call the API
              setTimeout(() => {
                setPreparing(false);
                setStatus("Dataset ready. Click Start Training to begin.");
              }, 3000);
            }}
          >
            {preparing ? "Preparing..." : "Prepare Dataset"}
          </button>
        </div>
      </div>

      {/* Status */}
      {status && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <p className="text-sm">{status}</p>
          {!preparing && !training && status.includes("ready") && (
            <button
              onClick={() => {
                setTraining(true);
                setStatus("Training LoRA... This will take 15-25 minutes.");
              }}
              className="mt-3 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium transition-colors"
            >
              Start Training
            </button>
          )}
        </div>
      )}

      {/* Info */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-xs text-[var(--text-secondary)] space-y-2">
        <p className="font-medium text-[var(--text-primary)]">Training Guide</p>
        <ul className="list-disc list-inside space-y-1">
          <li>Use 15-30 high-quality photos with varied angles, lighting, and expressions</li>
          <li>Close-up face shots work best — avoid group photos</li>
          <li>The trigger word is how you&apos;ll reference this person in prompts</li>
          <li>SDXL training takes ~15 min, FLUX takes ~25 min on RTX 5060 Ti</li>
          <li>After training, the LoRA appears in the Create tab and Queens tab</li>
        </ul>
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
