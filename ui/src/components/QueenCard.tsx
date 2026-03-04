"use client";

import type { QueenProfile } from "@/lib/api";
import { DNARadarMini } from "./DNARadar";

interface Props {
  queen: QueenProfile;
  selected?: boolean;
  onClick?: () => void;
}

export function QueenCard({ queen, selected = false, onClick }: Props) {
  // Top 3 dominant traits
  const topTraits = Object.entries(queen.dna)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([k]) => k.replace(/_/g, " "));

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left rounded-lg border p-3 transition-all
        ${
          selected
            ? "border-[var(--accent)] bg-[var(--accent)]/10 ring-1 ring-[var(--accent)]/30"
            : "border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--text-secondary)]"
        }
      `}
    >
      <div className="flex gap-3">
        {/* DNA Mini Radar */}
        <div className="flex-shrink-0">
          <DNARadarMini dna={queen.dna} className="opacity-80" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm truncate">{queen.name}</h3>
          <p className="text-xs text-[var(--text-secondary)] truncate">{queen.performer_ref}</p>

          {/* Top traits */}
          <div className="flex flex-wrap gap-1 mt-2">
            {topTraits.map((t) => (
              <span
                key={t}
                className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-secondary)] capitalize"
              >
                {t}
              </span>
            ))}
          </div>

          {/* Status indicators */}
          <div className="flex items-center gap-2 mt-2">
            {queen.lora_name && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400">
                LoRA
              </span>
            )}
            {queen.reference_images.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">
                {queen.reference_images.length} refs
              </span>
            )}
            {!queen.lora_name && queen.reference_images.length === 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
                ⚠ prompt only
              </span>
            )}
            <span className="text-[10px] text-[var(--text-secondary)]">
              {queen.scenes.length} scenes
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}
