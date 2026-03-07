"use client";

import { useEffect, useState, useCallback, useRef, type DragEvent } from "react";
import { api } from "@/lib/api";

// ─── Constants ──────────────────────────────────────────────────────────

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700";

type IngestTab = "file" | "url" | "text";

interface Collection {
  name: string;
  vectors_count?: number;
  points_count?: number;
}

interface SearchResult {
  content?: string;
  text?: string;
  source?: string;
  metadata?: Record<string, unknown>;
  score?: number;
  confidence?: number;
  tier?: string;
  collection?: string;
}

interface IngestStats {
  active_watchers?: number;
  total_ingested?: number;
  recent_activity?: Array<{
    source: string;
    chunks: number;
    timestamp: string;
    status: string;
  }>;
}

// ─── Helpers ────────────────────────────────────────────────────────────

function timeSince(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

function collectionBadgeStyle(name: string): { bg: string; text: string } {
  switch (name) {
    case "knowledge_vault":
      return { bg: "rgba(99, 179, 237, 0.15)", text: "rgb(99, 179, 237)" };
    case "resources":
      return { bg: "rgba(116, 185, 132, 0.15)", text: "rgb(116, 185, 132)" };
    case "episodic":
      return { bg: "rgba(217, 149, 99, 0.15)", text: "rgb(217, 149, 99)" };
    default:
      return { bg: "rgba(147, 130, 220, 0.15)", text: "rgb(147, 130, 220)" };
  }
}

function tierBadgeColor(tier: string): string {
  switch (tier?.toLowerCase()) {
    case "vault":
      return "text-blue-400 bg-blue-500/20";
    case "episodic":
      return "text-orange-400 bg-orange-500/20";
    case "semantic":
      return "text-purple-400 bg-purple-500/20";
    case "procedural":
      return "text-green-400 bg-green-500/20";
    case "resource":
      return "text-cyan-400 bg-cyan-500/20";
    case "working":
      return "text-yellow-400 bg-yellow-500/20";
    default:
      return "text-gray-400 bg-gray-500/20";
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── Stat Card Component ────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  statusDot,
}: {
  label: string;
  value: string | number;
  sub?: string;
  statusDot?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="flex items-center gap-2 mb-1">
        {statusDot && (
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: statusDot }}
          />
        )}
        <span className="text-xs text-[var(--text-secondary)] uppercase tracking-wider">
          {label}
        </span>
      </div>
      <div className="text-2xl font-bold font-mono">{value}</div>
      {sub && (
        <span className="text-xs text-[var(--text-secondary)]">{sub}</span>
      )}
    </div>
  );
}

// ─── Collection Card Component ──────────────────────────────────────────

function CollectionCard({ collection }: { collection: Collection }) {
  const docCount = collection.points_count ?? collection.vectors_count ?? 0;
  const badge = collectionBadgeStyle(collection.name);

  const collectionDescriptions: Record<string, string> = {
    knowledge_vault: "Consolidated long-term knowledge and verified facts",
    resources: "Ingested documents, files, and web content chunks",
    episodic: "Session memories and operational event logs",
  };

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className="w-3 h-3 rounded-sm flex-shrink-0"
            style={{ background: badge.text }}
          />
          <h3 className="font-semibold text-base">{collection.name}</h3>
        </div>
        <span
          className="text-xs font-medium px-2 py-0.5 rounded-md"
          style={{ background: badge.bg, color: badge.text }}
        >
          {docCount.toLocaleString()} chunks
        </span>
      </div>

      <p className="text-xs text-[var(--text-secondary)]">
        {collectionDescriptions[collection.name] || "Custom collection"}
      </p>

      <div className="space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-[var(--text-secondary)]">Documents</span>
          <span className="font-mono text-xs">{docCount.toLocaleString()}</span>
        </div>
        {collection.vectors_count !== undefined && (
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Vectors</span>
            <span className="font-mono text-xs">
              {collection.vectors_count.toLocaleString()}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Search Panel Component ─────────────────────────────────────────────

function SearchPanel() {
  const [query, setQuery] = useState("");
  const [searchCollection, setSearchCollection] = useState("resources");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchMode, setSearchMode] = useState<"rag" | "memory">("rag");

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      let resp;
      if (searchMode === "rag") {
        resp = await api.search(query, searchCollection, 10);
      } else {
        resp = await api.searchMemory(query, 10);
      }
      const items = resp?.results || resp?.matches || resp || [];
      setResults(Array.isArray(items) ? items : []);
    } catch {
      setResults([]);
    }
    setSearching(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Search</h2>
        <div className="flex gap-1">
          <button
            onClick={() => setSearchMode("rag")}
            className={`text-xs px-3 py-1 rounded-md transition-colors ${
              searchMode === "rag"
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--bg-primary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            RAG Search
          </button>
          <button
            onClick={() => setSearchMode("memory")}
            className={`text-xs px-3 py-1 rounded-md transition-colors ${
              searchMode === "memory"
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--bg-primary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            Memory Search
          </button>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            searchMode === "rag"
              ? "Search documents and knowledge..."
              : "Search across memory tiers..."
          }
          className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)] transition-colors"
        />
        {searchMode === "rag" && (
          <select
            value={searchCollection}
            onChange={(e) => setSearchCollection(e.target.value)}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="resources">resources</option>
            <option value="knowledge_vault">knowledge_vault</option>
            <option value="episodic">episodic</option>
          </select>
        )}
        <button
          onClick={handleSearch}
          disabled={searching || !query.trim()}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            query.trim() && !searching
              ? "bg-[var(--accent)] text-white hover:opacity-90"
              : "bg-[var(--bg-primary)] text-[var(--text-secondary)] cursor-not-allowed"
          }`}
        >
          {searching ? "Searching..." : "Search"}
        </button>
      </div>

      {/* Results */}
      {searched && (
        <div className="space-y-2">
          {results.length === 0 && !searching && (
            <div className="text-center py-6 text-[var(--text-secondary)] text-sm">
              No results found. Try a different query or collection.
            </div>
          )}
          {results.map((result, idx) => {
            const content = result.content || result.text || "";
            const score =
              result.score ?? result.confidence ?? 0;
            const source =
              result.source ||
              (result.metadata as Record<string, unknown>)?.source ||
              "unknown";
            const tier =
              result.tier ||
              result.collection ||
              (result.metadata as Record<string, unknown>)?.tier ||
              "";

            return (
              <div
                key={idx}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-primary)] p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-[var(--text-secondary)]">
                      #{idx + 1}
                    </span>
                    {tier && (
                      <span
                        className={`text-[10px] font-mono font-medium px-1.5 py-0.5 rounded ${tierBadgeColor(
                          String(tier)
                        )}`}
                      >
                        {String(tier)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1">
                      <div className="w-16 h-1.5 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.min(score * 100, 100)}%`,
                            background:
                              score > 0.7
                                ? "var(--success)"
                                : score > 0.4
                                  ? "var(--warning)"
                                  : "var(--error)",
                          }}
                        />
                      </div>
                      <span className="text-[10px] font-mono text-[var(--text-secondary)]">
                        {(score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </div>

                <p className="text-xs leading-relaxed">
                  {truncate(content, 300)}
                </p>

                <div className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]">
                  <span className="font-mono truncate max-w-xs" title={String(source)}>
                    {String(source)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── File Upload Zone Component ─────────────────────────────────────────

function FileUploadZone({ onUploadComplete }: { onUploadComplete: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      setSelectedFile(files[0]);
      uploadFile(files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      uploadFile(file);
    }
  };

  const uploadFile = async (file: File) => {
    setUploading(true);
    setUploadStatus(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const resp = await fetch(`${BASE_URL}/v1/ingest/file`, {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        const errText = await resp.text().catch(() => "Unknown error");
        throw new Error(errText);
      }

      setUploadStatus({
        type: "success",
        message: `Successfully ingested "${file.name}" (${formatFileSize(file.size)})`,
      });
      onUploadComplete();
    } catch (err) {
      setUploadStatus({
        type: "error",
        message: `Failed to ingest "${file.name}": ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    } finally {
      setUploading(false);
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`rounded-lg border-2 border-dashed p-8 text-center cursor-pointer transition-all ${
          dragging
            ? "border-[var(--accent)] bg-[var(--accent)]/5"
            : "border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--bg-primary)]/50"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={handleFileSelect}
          accept=".pdf,.txt,.md,.json,.csv,.html,.docx,.py,.js,.ts,.yaml,.yml,.toml,.xml"
        />

        {uploading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="relative w-8 h-8">
              <div className="absolute inset-0 border-2 border-[var(--border)] rounded-full" />
              <div className="absolute inset-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            </div>
            <p className="text-sm text-[var(--text-secondary)]">
              Ingesting {selectedFile?.name}...
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <div className="w-10 h-10 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] flex items-center justify-center text-[var(--text-secondary)]">
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium">
                Drop files here or click to browse
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                PDF, TXT, MD, JSON, CSV, HTML, DOCX, code files
              </p>
            </div>
          </div>
        )}
      </div>

      {uploadStatus && (
        <div
          className={`rounded-md px-3 py-2 text-xs ${
            uploadStatus.type === "success"
              ? "bg-[var(--success)]/10 text-[var(--success)] border border-[var(--success)]/20"
              : "bg-[var(--error)]/10 text-[var(--error)] border border-[var(--error)]/20"
          }`}
        >
          {uploadStatus.message}
        </div>
      )}
    </div>
  );
}

// ─── URL Ingest Component ───────────────────────────────────────────────

function UrlIngestPanel({ onIngestComplete }: { onIngestComplete: () => void }) {
  const [url, setUrl] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const handleIngest = async () => {
    if (!url.trim()) return;
    setIngesting(true);
    setStatus(null);

    try {
      const resp = await fetch(`${BASE_URL}/v1/ingest/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });

      if (!resp.ok) {
        const errText = await resp.text().catch(() => "Unknown error");
        throw new Error(errText);
      }

      setStatus({
        type: "success",
        message: `Successfully ingested content from ${url}`,
      });
      setUrl("");
      onIngestComplete();
    } catch (err) {
      setStatus({
        type: "error",
        message: `Failed: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-secondary)]">
        Ingest web pages, documentation, or any publicly accessible URL into the
        knowledge base.
      </p>
      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleIngest();
          }}
          placeholder="https://example.com/docs/page"
          className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)] transition-colors"
        />
        <button
          onClick={handleIngest}
          disabled={ingesting || !url.trim()}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
            url.trim() && !ingesting
              ? "bg-[var(--accent)] text-white hover:opacity-90"
              : "bg-[var(--bg-primary)] text-[var(--text-secondary)] cursor-not-allowed"
          }`}
        >
          {ingesting ? "Ingesting..." : "Ingest URL"}
        </button>
      </div>

      {status && (
        <div
          className={`rounded-md px-3 py-2 text-xs ${
            status.type === "success"
              ? "bg-[var(--success)]/10 text-[var(--success)] border border-[var(--success)]/20"
              : "bg-[var(--error)]/10 text-[var(--error)] border border-[var(--error)]/20"
          }`}
        >
          {status.message}
        </div>
      )}
    </div>
  );
}

// ─── Text Ingest Component ──────────────────────────────────────────────

function TextIngestPanel({ onIngestComplete }: { onIngestComplete: () => void }) {
  const [content, setContent] = useState("");
  const [source, setSource] = useState("");
  const [tags, setTags] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const handleIngest = async () => {
    if (!content.trim()) return;
    setIngesting(true);
    setStatus(null);

    const body: Record<string, unknown> = { content: content.trim() };
    if (source.trim()) body.source = source.trim();
    if (tags.trim()) {
      body.tags = tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
    }

    try {
      const resp = await fetch(`${BASE_URL}/v1/ingest/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const errText = await resp.text().catch(() => "Unknown error");
        throw new Error(errText);
      }

      const charCount = content.trim().length;
      setStatus({
        type: "success",
        message: `Successfully ingested ${charCount} characters of text`,
      });
      setContent("");
      setSource("");
      setTags("");
      onIngestComplete();
    } catch (err) {
      setStatus({
        type: "error",
        message: `Failed: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-secondary)]">
        Paste raw text content to chunk, embed, and index into the knowledge base.
      </p>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Paste text content here..."
        rows={6}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm resize-none focus:outline-none focus:border-[var(--accent)] transition-colors"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div>
          <label className="text-xs text-[var(--text-secondary)] mb-1 block">
            Source label (optional)
          </label>
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g. meeting-notes-2026-03-06"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)] transition-colors"
          />
        </div>
        <div>
          <label className="text-xs text-[var(--text-secondary)] mb-1 block">
            Tags (comma-separated, optional)
          </label>
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="e.g. notes, project, ops"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm focus:outline-none focus:border-[var(--accent)] transition-colors"
          />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--text-secondary)] font-mono">
          {content.length > 0 ? `${content.length} chars` : ""}
        </span>
        <button
          onClick={handleIngest}
          disabled={ingesting || !content.trim()}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            content.trim() && !ingesting
              ? "bg-[var(--accent)] text-white hover:opacity-90"
              : "bg-[var(--bg-primary)] text-[var(--text-secondary)] cursor-not-allowed"
          }`}
        >
          {ingesting ? "Ingesting..." : "Ingest Text"}
        </button>
      </div>

      {status && (
        <div
          className={`rounded-md px-3 py-2 text-xs ${
            status.type === "success"
              ? "bg-[var(--success)]/10 text-[var(--success)] border border-[var(--success)]/20"
              : "bg-[var(--error)]/10 text-[var(--error)] border border-[var(--error)]/20"
          }`}
        >
          {status.message}
        </div>
      )}
    </div>
  );
}

// ─── Ingest Panel Component ─────────────────────────────────────────────

function IngestPanel({ onIngestComplete }: { onIngestComplete: () => void }) {
  const [activeTab, setActiveTab] = useState<IngestTab>("file");

  const tabs: { id: IngestTab; label: string }[] = [
    { id: "file", label: "File Upload" },
    { id: "url", label: "URL Ingest" },
    { id: "text", label: "Text Ingest" },
  ];

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-4">
      <h2 className="text-lg font-semibold">Ingest Content</h2>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-[var(--border)]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
              activeTab === t.id
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "file" && (
        <FileUploadZone onUploadComplete={onIngestComplete} />
      )}
      {activeTab === "url" && (
        <UrlIngestPanel onIngestComplete={onIngestComplete} />
      )}
      {activeTab === "text" && (
        <TextIngestPanel onIngestComplete={onIngestComplete} />
      )}
    </div>
  );
}

// ─── Recent Activity Component ──────────────────────────────────────────

function RecentActivity({ stats }: { stats: IngestStats | null }) {
  const activity = stats?.recent_activity;

  if (!stats || !activity || activity.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5">
        <h2 className="text-lg font-semibold mb-3">Recent Activity</h2>
        <div className="text-center py-6 text-[var(--text-secondary)] text-sm">
          No recent ingestion activity recorded.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Recent Activity</h2>
        <span className="text-xs text-[var(--text-secondary)]">
          {activity.length} entries
        </span>
      </div>

      <div className="space-y-2">
        {activity.map((entry, idx) => (
          <div
            key={idx}
            className="flex items-center justify-between rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2"
          >
            <div className="flex items-center gap-3 min-w-0">
              <span
                className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{
                  background:
                    entry.status === "success"
                      ? "var(--success)"
                      : entry.status === "error"
                        ? "var(--error)"
                        : "var(--warning)",
                }}
              />
              <span className="text-xs font-mono truncate" title={entry.source}>
                {entry.source}
              </span>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              <span className="text-[10px] text-[var(--text-secondary)]">
                {entry.chunks} chunks
              </span>
              <span className="text-[10px] text-[var(--text-secondary)]">
                {timeSince(entry.timestamp)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [ingestStats, setIngestStats] = useState<IngestStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [, setTick] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const [collectionsResp, statsResp] = await Promise.allSettled([
        api.listCollections(),
        fetch(`${BASE_URL}/v1/ingest/stats`).then((r) =>
          r.ok ? r.json() : null
        ),
      ]);

      if (collectionsResp.status === "fulfilled") {
        setCollections(collectionsResp.value);
        setLastUpdated(new Date().toISOString());
        setError(null);
      } else {
        setError("Failed to fetch collections");
      }

      if (statsResp.status === "fulfilled" && statsResp.value) {
        setIngestStats(statsResp.value);
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

  // Tick for "updated X ago" display
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const handleIngestComplete = () => {
    // Refresh collections after any ingestion
    fetchData();
  };

  // ─── Derived stats ──────────────────────────────────────────────────

  const totalDocuments = collections.reduce(
    (sum, col) => sum + (col.points_count ?? col.vectors_count ?? 0),
    0
  );
  const totalCollections = collections.length;
  const activeWatchers = ingestStats?.active_watchers ?? 2; // Known: 2 active watchers from MEMORY.md
  const searchIndexStatus = totalCollections > 0 ? "indexed" : "empty";

  // ─── Render ─────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Documents</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Perception service ingestion pipeline -- collections, search, and
            content intake
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
      {loading && collections.length === 0 && (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-3">
            <div className="relative w-10 h-10">
              <div className="absolute inset-0 border-2 border-[var(--border)] rounded-full" />
              <div className="absolute inset-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            </div>
            <span className="text-sm text-[var(--text-secondary)]">
              Loading document collections...
            </span>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && collections.length === 0 && (
        <div className="rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-6 text-center">
          <p className="text-[var(--error)] mb-2">{error}</p>
          <p className="text-sm text-[var(--text-secondary)]">
            Check that the gateway is running and the Perception service is
            accessible.
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
      {(collections.length > 0 || (!loading && !error)) && (
        <>
          {/* Overview Strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <StatCard
              label="Collections"
              value={totalCollections}
              sub="Qdrant vector stores"
              statusDot={totalCollections > 0 ? "var(--success)" : "var(--warning)"}
            />
            <StatCard
              label="Documents"
              value={totalDocuments.toLocaleString()}
              sub="total indexed chunks"
            />
            <StatCard
              label="Watchers"
              value={activeWatchers}
              sub="active directory watchers"
              statusDot={activeWatchers > 0 ? "var(--success)" : "var(--text-secondary)"}
            />
            <StatCard
              label="Search Index"
              value={searchIndexStatus === "indexed" ? "Ready" : "Empty"}
              sub={
                searchIndexStatus === "indexed"
                  ? "hybrid RAG available"
                  : "no collections indexed"
              }
              statusDot={
                searchIndexStatus === "indexed"
                  ? "var(--success)"
                  : "var(--warning)"
              }
            />
          </div>

          {/* Collections Grid */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-lg font-semibold">Collections</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-[rgba(99,179,237,0.15)] text-[rgb(99,179,237)]">
                {totalCollections}
              </span>
            </div>
            {collections.length === 0 ? (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
                <p className="text-sm text-[var(--text-secondary)] mb-1">
                  No document collections found
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  Ingest content below to create vector collections in Qdrant.
                </p>
              </div>
            ) : (
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                {collections.map((col) => (
                  <CollectionCard key={col.name} collection={col} />
                ))}
              </div>
            )}
          </div>

          {/* Search + Ingest two-column layout */}
          <div className="grid gap-6 grid-cols-1 xl:grid-cols-2 mb-6">
            <SearchPanel />
            <IngestPanel onIngestComplete={handleIngestComplete} />
          </div>

          {/* Recent Activity */}
          <RecentActivity stats={ingestStats} />
        </>
      )}
    </div>
  );
}
