"use client";

import { useEffect, useState, useRef } from "react";
import { api } from "@/lib/api";

export default function DocumentsPage() {
  const [collections, setCollections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.listCollections().then(setCollections).finally(() => setLoading(false));
  }, []);

  const handleUpload = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700"}/v1/ingest/file`, {
        method: "POST",
        body: formData,
      });
      // Refresh collections
      const updated = await api.listCollections();
      setCollections(updated);
    } catch (err) {
      console.error("Upload failed:", err);
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Documents</h1>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={handleUpload}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-[var(--accent)] hover:bg-[var(--accent-hover)] rounded-lg text-sm font-medium transition-colors"
          >
            Upload Document
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-[var(--text-secondary)]">Loading collections...</p>
      ) : collections.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-secondary)]">
          <p className="text-lg mb-2">No document collections</p>
          <p>Upload documents to create a knowledge base for RAG.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {collections.map((col) => (
            <div
              key={col.name}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4 flex items-center justify-between"
            >
              <div>
                <h3 className="font-semibold">{col.name}</h3>
                <p className="text-sm text-[var(--text-secondary)]">
                  {col.vectors_count ?? col.points_count ?? 0} chunks
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
