"use client";

import { WorkspaceSwitcher } from "./workspace-switcher";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "D" },
  { href: "/chat", label: "Chat", icon: "C" },
  { href: "/generate", label: "Generate", icon: "G" },
  { href: "/models", label: "Models", icon: "M" },
  { href: "/memory", label: "Memory", icon: "W" },
  { href: "/agents", label: "Agents", icon: "A" },
  { href: "/documents", label: "Knowledge", icon: "K" },
  { href: "/nodes", label: "Nodes", icon: "N" },
];

const GALLERY_URL = `${typeof window !== "undefined" ? (process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.189:8700") : ""}/gallery`;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 h-screen border-r border-[var(--border)] bg-[var(--bg-secondary)] flex flex-col">
      {/* Logo */}
      <div className="p-4 border-b border-[var(--border)]">
        <h1 className="text-lg font-bold tracking-tight">Athanor</h1>
        <p className="text-xs text-[var(--text-secondary)]">Sovereign Cognitive Architecture</p>
      </div>

      {/* Workspace Switcher */}
      <div className="px-3 py-2 border-b border-[var(--border)]">
        <WorkspaceSwitcher />
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-2 space-y-1">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={clsx(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
              pathname === item.href
                ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]",
            )}
          >
            <span className="w-5 h-5 rounded bg-[var(--bg-tertiary)] flex items-center justify-center text-xs font-mono">
              {item.icon}
            </span>
            {item.label}
          </Link>
        ))}
        <div className="pt-2 mt-2 border-t border-[var(--border)]">
          <a
            href={GALLERY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <span className="w-5 h-5 rounded bg-[var(--bg-tertiary)] flex items-center justify-center text-xs">
              📷
            </span>
            Gallery
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">↗</span>
          </a>
        </div>
      </nav>

      {/* Status */}
      <div className="p-4 border-t border-[var(--border)]">
        <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          System Online
        </div>
      </div>
    </aside>
  );
}
