"use client";

import { useEffect, useState } from "react";
import { api, type ClusterHealth } from "@/lib/api";

export default function NodesPage() {
  const [health, setHealth] = useState<ClusterHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.clusterHealth().then(setHealth).finally(() => setLoading(false));
  }, []);

  const nodes = [
    { id: "node1", name: "Node 1", role: "Inference Primary", hardware: "EPYC 56C · 224GB · 4×5070Ti + 4090" },
    { id: "node2", name: "Node 2", role: "Inference + Fine-tune", hardware: "TR 24C · 128GB · 5090 + 5060Ti" },
    { id: "vault", name: "VAULT", role: "Storage + Vector DB", hardware: "R9 9950X · 128GB · 180TB HDD" },
    { id: "desk", name: "DESK", role: "UI + Orchestrator", hardware: "i7-13700K · 64GB · RTX 3060" },
    { id: "dev", name: "DEV", role: "Development + CI/CD", hardware: "R9 9900X · 64GB · 5060Ti" },
    { id: "mobile", name: "MOBILE", role: "Remote Client", hardware: "R9 5900HX · 64GB · 3070M" },
  ];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Cluster Nodes</h1>

      <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
        {nodes.map((node) => {
          const serviceHealth = health?.[node.id];
          const isOnline = serviceHealth && !("error" in serviceHealth);

          return (
            <div
              key={node.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-lg">{node.name}</h3>
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    loading
                      ? "bg-gray-500 animate-pulse"
                      : isOnline
                        ? "bg-green-500"
                        : "bg-red-500"
                  }`}
                />
              </div>
              <p className="text-sm text-[var(--accent)] mb-1">{node.role}</p>
              <p className="text-xs text-[var(--text-secondary)]">{node.hardware}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
