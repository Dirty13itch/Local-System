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
    { id: "foundry", name: "FOUNDRY", role: "Heavy Inference · Agents · Vector DB", hardware: "Specs from auto-discovery" },
    { id: "workshop", name: "WORKSHOP", role: "Fast Inference · Creative · Dashboard", hardware: "Specs from auto-discovery" },
    { id: "vault", name: "VAULT", role: "Storage · Routing · Monitoring · HA · Media", hardware: "Specs from auto-discovery" },
    { id: "dev", name: "DEV", role: "Operations Center · Claude Code", hardware: "Specs from auto-discovery" },
    { id: "desk", name: "DESK", role: "Daily Windows Workstation", hardware: "Specs from auto-discovery" },
    { id: "mobile", name: "MOBILE", role: "Laptop · Remote Access", hardware: "Asus ROG Strix G17" },
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
