"use client";

import { useEffect, useState, useCallback } from "react";
import {
  api,
  type AgentInfo,
  type AgentActivity,
  type AgentSchedule,
} from "@/lib/api";

// ─── Tab types ────────────────────────────────────────────────────────

type Tab = "overview" | "activity" | "schedules" | "tasks";

// ─── Helper: format relative time ────────────────────────────────────

function timeAgo(timestamp: string | number): string {
  const t = typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp * 1000;
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

// ─── Trust grade styling ─────────────────────────────────────────────

function gradeColor(grade: string): string {
  switch (grade) {
    case "A": return "text-green-400 bg-green-500/20";
    case "B": return "text-blue-400 bg-blue-500/20";
    case "C": return "text-yellow-400 bg-yellow-500/20";
    case "D": return "text-orange-400 bg-orange-500/20";
    case "F": return "text-red-400 bg-red-500/20";
    default: return "text-gray-400 bg-gray-500/20";
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "online": return "bg-green-500";
    case "offline": return "bg-red-500";
    case "error": return "bg-orange-500";
    default: return "bg-gray-500";
  }
}

// ─── Main Page ────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [serverUrl, setServerUrl] = useState("");
  const [serverStatus, setServerStatus] = useState<string>("checking");
  const [activity, setActivity] = useState<AgentActivity[]>([]);
  const [schedules, setSchedules] = useState<AgentSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [taskAgent, setTaskAgent] = useState("");
  const [taskPrompt, setTaskPrompt] = useState("");
  const [taskResult, setTaskResult] = useState<string | null>(null);
  const [taskSubmitting, setTaskSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [agentData, healthData] = await Promise.all([
        api.listAgents(),
        api.agentServerHealth(),
      ]);
      setAgents(agentData.agents);
      setServerUrl(agentData.server_url);
      setServerStatus(healthData.status);
    } catch {
      setServerStatus("offline");
    }
    setLoading(false);
  }, []);

  // Load tab-specific data
  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab === "activity") {
      api.getAgentActivity(50).then(setActivity);
    } else if (tab === "schedules") {
      api.getAgentSchedules().then(setSchedules);
    }
  }, [tab]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleSubmitTask = async () => {
    if (!taskAgent || !taskPrompt) return;
    setTaskSubmitting(true);
    setTaskResult(null);
    try {
      const result = await api.submitAgentTask({ agent: taskAgent, prompt: taskPrompt });
      setTaskResult(JSON.stringify(result, null, 2));
      setTaskPrompt("");
    } catch (e) {
      setTaskResult(`Error: ${e}`);
    }
    setTaskSubmitting(false);
  };

  const handleFeedback = async (agentName: string, vote: "up" | "down") => {
    await api.submitAgentFeedback({ agent: agentName, vote });
    refresh();
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Agents" },
    { id: "activity", label: "Activity" },
    { id: "schedules", label: "Schedules" },
    { id: "tasks", label: "Submit Task" },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agent System</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            9 autonomous agents · 72 tools · Proactive scheduling · Trust & escalation
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              serverStatus === "online"
                ? "bg-green-500"
                : serverStatus === "checking"
                  ? "bg-gray-500 animate-pulse"
                  : "bg-red-500"
            }`}
          />
          <span className="text-sm text-[var(--text-secondary)]">
            {serverStatus === "online" ? "Server Online" : serverStatus === "checking" ? "Checking..." : "Server Offline"}
          </span>
          <button
            onClick={refresh}
            className="text-xs px-3 py-1.5 rounded border border-[var(--border)] hover:border-[var(--accent)] transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-[var(--border)]">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
              tab === t.id
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && (
        <OverviewTab
          agents={agents}
          loading={loading}
          serverUrl={serverUrl}
          onFeedback={handleFeedback}
        />
      )}
      {tab === "activity" && <ActivityTab activity={activity} />}
      {tab === "schedules" && <SchedulesTab schedules={schedules} />}
      {tab === "tasks" && (
        <TasksTab
          agents={agents}
          taskAgent={taskAgent}
          taskPrompt={taskPrompt}
          taskResult={taskResult}
          taskSubmitting={taskSubmitting}
          onAgentChange={setTaskAgent}
          onPromptChange={setTaskPrompt}
          onSubmit={handleSubmitTask}
        />
      )}
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────

function OverviewTab({
  agents,
  loading,
  serverUrl,
  onFeedback,
}: {
  agents: AgentInfo[];
  loading: boolean;
  serverUrl: string;
  onFeedback: (agent: string, vote: "up" | "down") => void;
}) {
  if (loading) {
    return <p className="text-[var(--text-secondary)]">Loading agents...</p>;
  }

  if (agents.length === 0) {
    return (
      <div className="text-center py-12 text-[var(--text-secondary)]">
        <p className="text-lg mb-2">No agents found</p>
        <p className="text-sm">
          Agent server may be offline. Expected at {serverUrl || "FOUNDRY:9000"}
        </p>
      </div>
    );
  }

  // Separate proactive vs reactive
  const proactive = agents.filter((a) => a.type === "proactive");
  const reactive = agents.filter((a) => a.type === "reactive");

  return (
    <div className="space-y-6">
      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Agents", value: agents.length },
          { label: "Online", value: agents.filter((a) => a.status === "online").length },
          { label: "Proactive", value: proactive.length },
          { label: "Total Tools", value: agents.reduce((sum, a) => sum + a.tools.length, 0) },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-center"
          >
            <p className="text-2xl font-bold">{stat.value}</p>
            <p className="text-xs text-[var(--text-secondary)]">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Proactive agents */}
      {proactive.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3">Proactive Agents</h2>
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            Run autonomously on schedules — media monitoring, home automation, knowledge indexing
          </p>
          <div className="grid gap-3 grid-cols-1 md:grid-cols-2">
            {proactive.map((agent) => (
              <AgentCard key={agent.name} agent={agent} onFeedback={onFeedback} />
            ))}
          </div>
        </section>
      )}

      {/* Reactive agents */}
      {reactive.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3">Reactive Agents</h2>
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            Respond to user requests — code review, research, creative writing
          </p>
          <div className="grid gap-3 grid-cols-1 md:grid-cols-2">
            {reactive.map((agent) => (
              <AgentCard key={agent.name} agent={agent} onFeedback={onFeedback} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ─── Agent Card ───────────────────────────────────────────────────────

function AgentCard({
  agent,
  onFeedback,
}: {
  agent: AgentInfo;
  onFeedback: (agent: string, vote: "up" | "down") => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${statusColor(agent.status)}`} />
          <h3 className="font-semibold text-sm">{agent.name}</h3>
        </div>
        <div className="flex items-center gap-2">
          {agent.trust && (
            <span
              className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${gradeColor(agent.trust.grade)}`}
            >
              {agent.trust.grade} ({(agent.trust.score * 100).toFixed(0)}%)
            </span>
          )}
          <span className="text-xs text-[var(--text-secondary)]">
            {agent.tools.length} tools
          </span>
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-[var(--text-secondary)] mb-3">{agent.description}</p>

      {/* Schedule */}
      {agent.schedule && (
        <p className="text-xs text-[var(--accent)] mb-2">⏰ {agent.schedule}</p>
      )}

      {/* Status note */}
      {agent.status_note && (
        <p className="text-xs text-orange-400 mb-2">{agent.status_note}</p>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          {expanded ? "▾ Hide tools" : "▸ Show tools"}
        </button>
        <div className="flex gap-1">
          <button
            onClick={() => onFeedback(agent.name, "up")}
            className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-green-500 hover:text-green-400 transition-colors"
            title="Good work"
          >
            👍
          </button>
          <button
            onClick={() => onFeedback(agent.name, "down")}
            className="text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-red-500 hover:text-red-400 transition-colors"
            title="Needs improvement"
          >
            👎
          </button>
        </div>
      </div>

      {/* Expanded tool list */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <div className="flex flex-wrap gap-1">
            {agent.tools.map((tool) => (
              <span
                key={tool}
                className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-secondary)]"
              >
                {tool}
              </span>
            ))}
          </div>
          {agent.trust && (
            <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] text-[var(--text-secondary)]">
              <div>
                Feedback: {agent.trust.feedback.up}↑ {agent.trust.feedback.down}↓
              </div>
              <div>
                Escalations: {agent.trust.escalation.approved}✓ {agent.trust.escalation.rejected}✗
              </div>
              <div>Samples: {agent.trust.samples}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Activity Tab ─────────────────────────────────────────────────────

function ActivityTab({ activity }: { activity: AgentActivity[] }) {
  if (activity.length === 0) {
    return (
      <div className="text-center py-12 text-[var(--text-secondary)]">
        <p className="text-lg mb-2">No recent activity</p>
        <p className="text-sm">Agents will log their actions here as they work</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-[var(--text-secondary)] mb-3">
        What agents have been doing proactively — most recent first
      </p>
      {activity.map((entry, i) => (
        <div
          key={i}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3"
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[var(--accent)]">{entry.agent}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-secondary)]">
                {entry.action_type}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]">
              <span>{formatDuration(entry.duration_ms)}</span>
              <span>{timeAgo(entry.timestamp)}</span>
            </div>
          </div>
          {entry.input_summary && (
            <p className="text-xs text-[var(--text-secondary)] truncate">
              → {entry.input_summary}
            </p>
          )}
          {entry.output_summary && (
            <p className="text-xs mt-1 truncate">{entry.output_summary}</p>
          )}
          {entry.tools_used.length > 0 && (
            <div className="flex gap-1 mt-1">
              {entry.tools_used.map((tool) => (
                <span
                  key={tool}
                  className="text-[9px] font-mono px-1 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-secondary)]"
                >
                  {tool}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Schedules Tab ────────────────────────────────────────────────────

function SchedulesTab({ schedules }: { schedules: AgentSchedule[] }) {
  if (schedules.length === 0) {
    return (
      <div className="text-center py-12 text-[var(--text-secondary)]">
        <p className="text-lg mb-2">No schedules found</p>
        <p className="text-sm">Proactive agents run on configurable intervals</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-secondary)] mb-3">
        Proactive agent schedules — when each agent runs autonomously
      </p>
      <div className="rounded-lg border border-[var(--border)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--bg-secondary)] text-left text-xs text-[var(--text-secondary)]">
              <th className="px-4 py-2">Agent</th>
              <th className="px-4 py-2">Interval</th>
              <th className="px-4 py-2">Priority</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Last Run</th>
              <th className="px-4 py-2">Next In</th>
            </tr>
          </thead>
          <tbody>
            {schedules.map((s) => (
              <tr key={s.agent} className="border-t border-[var(--border)]">
                <td className="px-4 py-2 font-medium">{s.agent}</td>
                <td className="px-4 py-2 text-[var(--text-secondary)]">{s.interval_human}</td>
                <td className="px-4 py-2">
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      s.priority === "high"
                        ? "bg-red-500/20 text-red-400"
                        : s.priority === "medium"
                          ? "bg-yellow-500/20 text-yellow-400"
                          : "bg-gray-500/20 text-gray-400"
                    }`}
                  >
                    {s.priority}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`w-2 h-2 rounded-full inline-block ${
                      s.enabled ? "bg-green-500" : "bg-gray-500"
                    }`}
                  />
                  <span className="ml-1.5 text-xs">{s.enabled ? "Active" : "Paused"}</span>
                </td>
                <td className="px-4 py-2 text-xs text-[var(--text-secondary)]">
                  {s.last_run ? timeAgo(s.last_run) : "Never"}
                </td>
                <td className="px-4 py-2 text-xs text-[var(--text-secondary)]">
                  {s.next_run_in > 0 ? formatDuration(s.next_run_in * 1000) : "Now"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tasks Tab ────────────────────────────────────────────────────────

function TasksTab({
  agents,
  taskAgent,
  taskPrompt,
  taskResult,
  taskSubmitting,
  onAgentChange,
  onPromptChange,
  onSubmit,
}: {
  agents: AgentInfo[];
  taskAgent: string;
  taskPrompt: string;
  taskResult: string | null;
  taskSubmitting: boolean;
  onAgentChange: (v: string) => void;
  onPromptChange: (v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-xs text-[var(--text-secondary)]">
        Send a task directly to a specific agent for execution
      </p>

      {/* Agent selector */}
      <div>
        <label className="text-sm font-medium mb-1 block">Agent</label>
        <select
          value={taskAgent}
          onChange={(e) => onAgentChange(e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm"
        >
          <option value="">Select an agent...</option>
          {agents
            .filter((a) => a.status === "online")
            .map((a) => (
              <option key={a.name} value={a.name}>
                {a.name} — {a.description}
              </option>
            ))}
        </select>
      </div>

      {/* Prompt */}
      <div>
        <label className="text-sm font-medium mb-1 block">Task Prompt</label>
        <textarea
          value={taskPrompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder="What should this agent do?"
          rows={4}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm resize-none"
        />
      </div>

      {/* Submit */}
      <button
        onClick={onSubmit}
        disabled={!taskAgent || !taskPrompt || taskSubmitting}
        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
          taskAgent && taskPrompt && !taskSubmitting
            ? "bg-[var(--accent)] text-white hover:opacity-90"
            : "bg-[var(--bg-secondary)] text-[var(--text-secondary)] cursor-not-allowed"
        }`}
      >
        {taskSubmitting ? "Submitting..." : "Submit Task"}
      </button>

      {/* Result */}
      {taskResult && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h3 className="text-sm font-semibold mb-2">Result</h3>
          <pre className="text-xs font-mono whitespace-pre-wrap overflow-auto max-h-96 text-[var(--text-secondary)]">
            {taskResult}
          </pre>
        </div>
      )}
    </div>
  );
}
