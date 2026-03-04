"use client";

interface Props {
  progress: number; // 0-100
  label?: string;
  showPercent?: boolean;
  className?: string;
}

export function ProgressBar({ progress, label, showPercent = true, className = "" }: Props) {
  const clamped = Math.max(0, Math.min(100, progress));

  return (
    <div className={`w-full ${className}`}>
      {(label || showPercent) && (
        <div className="flex justify-between items-center mb-1.5">
          {label && <span className="text-xs text-[var(--text-secondary)]">{label}</span>}
          {showPercent && <span className="text-xs font-mono text-[var(--text-secondary)]">{Math.round(clamped)}%</span>}
        </div>
      )}
      <div className="h-2 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--accent)] transition-all duration-300 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

interface SpinnerProps {
  label?: string;
  className?: string;
}

export function GeneratingSpinner({ label = "Generating...", className = "" }: SpinnerProps) {
  return (
    <div className={`flex flex-col items-center gap-3 py-8 ${className}`}>
      <div className="relative w-12 h-12">
        <div className="absolute inset-0 border-2 border-[var(--border)] rounded-full" />
        <div className="absolute inset-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
      </div>
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
    </div>
  );
}
