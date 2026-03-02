"use client";

import { useEffect, useState } from "react";
import { api, type Model } from "@/lib/api";

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listModels().then(setModels).finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Models</h1>

      {loading ? (
        <p className="text-[var(--text-secondary)]">Loading models...</p>
      ) : models.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">No models loaded</p>
          <p>Pull a model using the Model Manager or Ollama CLI.</p>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {models.map((model) => (
            <div
              key={model.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold truncate">{model.name}</h3>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    model.loaded
                      ? "bg-green-500/20 text-green-400"
                      : "bg-gray-500/20 text-gray-400"
                  }`}
                >
                  {model.loaded ? "Loaded" : "Available"}
                </span>
              </div>
              <div className="text-sm text-[var(--text-secondary)] space-y-1">
                <p>Backend: {model.backend}</p>
                {model.parameter_count && <p>Parameters: {model.parameter_count}</p>}
                {model.quantization && <p>Quantization: {model.quantization}</p>}
                {model.node && <p>Node: {model.node}</p>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
