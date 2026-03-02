"use client";

import { useEffect, useState } from "react";
import { api, WorkingContext } from "@/lib/api";

export default function MemoryPage() {
  const [working, setWorking] = useState<WorkingContext | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getWorkingMemory().then(setWorking).catch(console.error);
  }, []);

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try {
      const data = await api.searchMemory(searchQuery);
      setSearchResults(data.results || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Memory</h1>
      <p className="text-sm text-[var(--text-secondary)]">
        6-tier cognitive memory system — Procedural, Working, Episodic, Semantic, Resource, Knowledge Vault
      </p>

      {/* Working Memory */}
      <section className="border border-[var(--border)] rounded-lg p-4">
        <h2 className="text-lg font-semibold mb-3">Working Memory</h2>
        {working ? (
          <div className="space-y-2 text-sm">
            <div>
              <span className="text-[var(--text-secondary)]">Active Task: </span>
              <span>{working.active_task || "None"}</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)]">Priorities: </span>
              <span>{working.active_priorities?.join(", ") || "None"}</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)]">Unresolved: </span>
              <span>{working.unresolved_questions?.join(", ") || "None"}</span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-secondary)]">Loading...</p>
        )}
      </section>

      {/* Memory Search */}
      <section className="border border-[var(--border)] rounded-lg p-4">
        <h2 className="text-lg font-semibold mb-3">Search Memory</h2>
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search across all memory tiers..."
            className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] text-sm"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm hover:opacity-90"
          >
            {loading ? "..." : "Search"}
          </button>
        </div>

        {searchResults.length > 0 && (
          <div className="space-y-2">
            {searchResults.map((r: any, i: number) => (
              <div key={i} className="p-3 rounded bg-[var(--bg-tertiary)] text-sm">
                <div className="flex justify-between mb-1">
                  <span className="text-xs px-2 py-0.5 rounded bg-[var(--accent)]/20 text-[var(--accent)]">
                    {r.tier}
                  </span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {(r.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <p>{r.content}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
