"use client";

import { useState, useEffect, useRef } from "react";

interface Workspace {
  slug: string;
  name: string;
  type: string;
  icon: string;
  default_model: string;
  description: string;
}

const MIND_URL = process.env.NEXT_PUBLIC_MIND_URL || "http://localhost:8710";

// Stable session ID per browser tab
function getSessionId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = sessionStorage.getItem("ls-session-id");
  if (!id) {
    id = `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem("ls-session-id", id);
  }
  return id;
}

export function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [active, setActive] = useState<string>("infrastructure");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Load workspaces + active on mount
  useEffect(() => {
    async function load() {
      try {
        const [wsResp, activeResp] = await Promise.all([
          fetch(`${MIND_URL}/v1/workspaces`),
          fetch(`${MIND_URL}/v1/workspaces/active/${getSessionId()}`),
        ]);
        if (wsResp.ok) {
          const data = await wsResp.json();
          setWorkspaces(data.workspaces || []);
        }
        if (activeResp.ok) {
          const data = await activeResp.json();
          if (data.slug) setActive(data.slug);
        }
      } catch {
        // MIND service may be down
      }
    }
    load();
  }, []);

  async function switchWorkspace(slug: string) {
    setLoading(true);
    try {
      const resp = await fetch(
        `${MIND_URL}/v1/workspaces/active/${getSessionId()}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug }),
        }
      );
      if (resp.ok) {
        setActive(slug);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
      setOpen(false);
    }
  }

  const activeWs = workspaces.find((w) => w.slug === active);

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm
                   bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)]
                   border border-[var(--border)] transition-colors w-full"
        disabled={loading}
      >
        <span className="w-6 h-6 rounded flex items-center justify-center
                         bg-[var(--accent)] text-[var(--bg-primary)] text-xs font-bold">
          {activeWs?.icon || "?"}
        </span>
        <span className="flex-1 text-left truncate font-medium">
          {activeWs?.name || "Loading..."}
        </span>
        <svg
          className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 mt-1 z-50
                        bg-[var(--bg-secondary)] border border-[var(--border)]
                        rounded-lg shadow-lg overflow-hidden max-h-[60vh] overflow-y-auto">
          {workspaces.map((ws) => (
            <button
              key={ws.slug}
              onClick={() => switchWorkspace(ws.slug)}
              className={`flex items-center gap-3 px-3 py-2.5 w-full text-left
                         hover:bg-[var(--bg-hover)] transition-colors
                         ${ws.slug === active ? "bg-[var(--bg-tertiary)]" : ""}`}
            >
              <span className={`w-6 h-6 rounded flex items-center justify-center
                               text-xs font-bold shrink-0
                               ${ws.slug === active
                                 ? "bg-[var(--accent)] text-[var(--bg-primary)]"
                                 : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)]"}`}>
                {ws.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{ws.name}</div>
                <div className="text-xs text-[var(--text-secondary)] truncate">
                  {ws.description}
                </div>
              </div>
              {ws.slug === active && (
                <svg className="w-4 h-4 text-[var(--accent)] shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
