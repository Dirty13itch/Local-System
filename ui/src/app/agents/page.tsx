"use client";

import { useEffect, useState } from "react";
import { api, CognitiveState } from "@/lib/api";

const SPECIALISTS = [
  { id: "research", name: "Research Agent", description: "Autonomous research, cross-domain connections" },
  { id: "coding", name: "Coding Agent", description: "Code generation, debugging, architecture" },
  { id: "creative", name: "Creative Agent", description: "Empire of Broken Queens — dialogue, characters" },
  { id: "building_science", name: "Building Science", description: "HERS, RESNET, IECC, ASHRAE" },
  { id: "media", name: "Media Agent", description: "Content tagging, 224TB library management" },
  { id: "infrastructure", name: "Infra Agent", description: "Self-monitoring, health, optimization" },
];

export default function AgentsPage() {
  const [cognitive, setCognitive] = useState<CognitiveState | null>(null);

  useEffect(() => {
    api.getCognitiveState().then(setCognitive).catch(console.error);
  }, []);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Cognitive Workspace</h1>
      <p className="text-sm text-[var(--text-secondary)]">
        Global Workspace Theory — specialist agents compete for attention and broadcast results
      </p>

      {/* Cognitive State */}
      {cognitive && (
        <section className="border border-[var(--border)] rounded-lg p-4">
          <h2 className="text-lg font-semibold mb-3">Continuous State Tensor</h2>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-[var(--text-secondary)]">Active Specialist</span>
              <p className="font-mono">{cognitive.active_specialist || "None"}</p>
            </div>
            <div>
              <span className="text-[var(--text-secondary)]">Attention Focus</span>
              <p className="font-mono">{cognitive.attention_focus || "Idle"}</p>
            </div>
            <div>
              <span className="text-[var(--text-secondary)]">Cycle Count</span>
              <p className="font-mono">{cognitive.cycle_count}</p>
            </div>
          </div>
        </section>
      )}

      {/* Specialists */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Specialist Modules</h2>
        <div className="grid grid-cols-2 gap-3">
          {SPECIALISTS.map((s) => (
            <div
              key={s.id}
              className="border border-[var(--border)] rounded-lg p-4 hover:border-[var(--accent)] transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium text-sm">{s.name}</h3>
                <span
                  className={`w-2 h-2 rounded-full ${
                    cognitive?.active_specialist === s.id ? "bg-green-500" : "bg-[var(--text-secondary)]"
                  }`}
                />
              </div>
              <p className="text-xs text-[var(--text-secondary)]">{s.description}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
