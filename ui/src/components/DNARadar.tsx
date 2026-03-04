"use client";

import type { QueenDNA } from "@/lib/api";

const TRAITS: { key: keyof QueenDNA; label: string; short: string }[] = [
  { key: "dominance", label: "Dominance", short: "DOM" },
  { key: "submission", label: "Submission", short: "SUB" },
  { key: "exhibitionism", label: "Exhibitionism", short: "EXH" },
  { key: "voyeurism", label: "Voyeurism", short: "VOY" },
  { key: "nurturing", label: "Nurturing", short: "NUR" },
  { key: "corruption", label: "Corruption", short: "COR" },
  { key: "possessiveness", label: "Possessiveness", short: "POS" },
  { key: "devotion", label: "Devotion", short: "DEV" },
  { key: "playfulness", label: "Playfulness", short: "PLY" },
  { key: "intensity", label: "Intensity", short: "INT" },
  { key: "ritualism", label: "Ritualism", short: "RIT" },
  { key: "spontaneity", label: "Spontaneity", short: "SPO" },
  { key: "emotional_openness", label: "Emotional Openness", short: "EMO" },
  { key: "guardedness", label: "Guardedness", short: "GRD" },
  { key: "sensory_focus", label: "Sensory Focus", short: "SEN" },
  { key: "intellectual_arousal", label: "Intellectual Arousal", short: "INA" },
  { key: "power_exchange", label: "Power Exchange", short: "PWR" },
  { key: "intimacy_threshold", label: "Intimacy Threshold", short: "ITH" },
  { key: "taboo_comfort", label: "Taboo Comfort", short: "TAB" },
];

interface Props {
  dna: QueenDNA;
  size?: number;
  showLabels?: boolean;
  className?: string;
}

export function DNARadar({ dna, size = 280, showLabels = true, className = "" }: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const maxR = size * 0.38;
  const labelR = size * 0.46;
  const n = TRAITS.length;
  const angleStep = (2 * Math.PI) / n;

  const point = (i: number, val: number) => {
    const angle = angleStep * i - Math.PI / 2;
    const r = (val / 10) * maxR;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  const labelPoint = (i: number) => {
    const angle = angleStep * i - Math.PI / 2;
    return { x: cx + labelR * Math.cos(angle), y: cy + labelR * Math.sin(angle) };
  };

  // Build data polygon
  const dataPoints = TRAITS.map((t, i) => point(i, dna[t.key] ?? 5));
  const dataPath = dataPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") + " Z";

  // Grid rings at 2, 4, 6, 8, 10
  const rings = [2, 4, 6, 8, 10];

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className={className} width={size} height={size}>
      {/* Grid rings */}
      {rings.map((val) => {
        const pts = Array.from({ length: n }, (_, i) => point(i, val));
        const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") + " Z";
        return (
          <path
            key={val}
            d={path}
            fill="none"
            stroke="var(--border)"
            strokeWidth={val === 10 ? 1.5 : 0.5}
            opacity={val === 10 ? 0.6 : 0.3}
          />
        );
      })}

      {/* Axis lines */}
      {TRAITS.map((_, i) => {
        const p = point(i, 10);
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={p.x}
            y2={p.y}
            stroke="var(--border)"
            strokeWidth={0.5}
            opacity={0.3}
          />
        );
      })}

      {/* Data fill */}
      <path d={dataPath} fill="var(--accent)" fillOpacity={0.15} stroke="var(--accent)" strokeWidth={2} />

      {/* Data points */}
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="var(--accent)" />
      ))}

      {/* Labels */}
      {showLabels &&
        TRAITS.map((t, i) => {
          const lp = labelPoint(i);
          return (
            <text
              key={t.key}
              x={lp.x}
              y={lp.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size < 200 ? 7 : 9}
              fill="var(--text-secondary)"
              className="select-none"
            >
              {size < 200 ? t.short : t.short}
            </text>
          );
        })}
    </svg>
  );
}

/** Mini version — no labels, for cards */
export function DNARadarMini({ dna, className = "" }: { dna: QueenDNA; className?: string }) {
  return <DNARadar dna={dna} size={120} showLabels={false} className={className} />;
}
