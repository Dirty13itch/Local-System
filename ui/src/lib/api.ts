/**
 * API client for the Local-System gateway.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700";

export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}


export interface Workspace {
  slug: string;
  name: string;
  type: string;
  icon: string;
  default_model: string;
  description: string;
}
export interface ChatRequest {
  model: string;
  messages: Message[];
  temperature?: number;
  max_tokens?: number;
  stream?: boolean;
}

export interface Model {
  id: string;
  name: string;
  backend: string;
  size_bytes: number;
  parameter_count: string;
  quantization: string;
  loaded: boolean;
  node: string;
}

export interface WorkingContext {
  active_task: string | null;
  active_priorities: string[];
  unresolved_questions: string[];
}

export interface CognitiveState {
  active_specialist: string | null;
  attention_focus: string;
  cycle_count: number;
}

// ─── Agent Server Types ────────────────────────────────────────────────

export interface AgentTrust {
  score: number;
  grade: string;
  feedback: { up: number; down: number; total: number };
  escalation: { approved: number; rejected: number; total: number };
  samples: number;
}

export interface AgentInfo {
  name: string;
  description: string;
  tools: string[];
  type: "proactive" | "reactive";
  schedule: string | null;
  status: "online" | "offline" | "error";
  status_note: string | null;
  trust?: AgentTrust;
}

export interface AgentActivity {
  agent: string;
  action_type: string;
  input_summary: string;
  output_summary: string;
  tools_used: string[];
  duration_ms: number;
  timestamp: string;
}

export interface AgentSchedule {
  agent: string;
  interval_seconds: number;
  interval_human: string;
  enabled: boolean;
  last_run: number | null;
  next_run_in: number;
  priority: string;
}

export type ClusterHealth = Record<string, Record<string, unknown>>;

// ─── Node Status Types ──────────────────────────────────────────────────

export interface GpuStatus {
  index: number;
  name: string;
  utilization_percent: number;
  vram_used_mb: number;
  vram_total_mb: number;
  temperature_c: number;
  power_watts: number;
}

export interface NodeStatus {
  name: string;
  ip: string;
  online: boolean;
  uptime_hours: number;
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  disk_used_gb: number;
  disk_total_gb: number;
  gpus: GpuStatus[];
  services: string[];
}

export interface NodesResponse {
  nodes: NodeStatus[];
  timestamp: string;
}

// ─── Model Info Types ────────────────────────────────────────────────────

export interface ModelDetail {
  alias: string;
  model_name: string;
  provider: string;
  api_base: string | null;
  node: string | null;
  mode: string | null;
  is_local: boolean;
  status: string;
}

export interface ModelsInfoResponse {
  models: ModelDetail[];
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async health(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/health`);
    return resp.json();
  }

  async clusterHealth(): Promise<ClusterHealth> {
    const resp = await fetch(`${this.baseUrl}/health/cluster`);
    return resp.json();
  }

  async getNodeStatus(): Promise<NodesResponse> {
    const resp = await fetch(`${this.baseUrl}/v1/nodes/status`);
    return resp.json();
  }

  async getModelInfo(): Promise<ModelsInfoResponse> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/models/info`);
      if (!resp.ok) return { models: [] };
      return resp.json();
    } catch {
      return { models: [] };
    }
  }

  async listModels(): Promise<Model[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/models`);
      return resp.json();
    } catch {
      return [];
    }
  }

  async chat(request: ChatRequest): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    return resp.json();
  }

  async chatStream(
    request: ChatRequest,
    onChunk: (text: string) => void,
  ): Promise<void> {
    const resp = await fetch(`${this.baseUrl}/v1/chat/completions/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...request, stream: true }),
    });

    if (!resp.body) throw new Error("No response body");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value, { stream: true });
      const lines = text.split("\n");

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6);
        if (payload === "[DONE]") return;

        try {
          const data = JSON.parse(payload);
          const content = data.choices?.[0]?.delta?.content || data.delta;
          if (content) {
            onChunk(content);
          }
        } catch {
          // Skip malformed chunks
        }
      }
    }
  }

  // Memory endpoints
  async getWorkingMemory(): Promise<WorkingContext> {
    const resp = await fetch(`${this.baseUrl}/v1/memory/working`);
    return resp.json();
  }

  async searchMemory(query: string, topK = 10, tiers?: string[]) {
    const body: Record<string, unknown> = { query, top_k: topK };
    if (tiers && tiers.length > 0) body.tiers = tiers;
    const resp = await fetch(`${this.baseUrl}/v1/memory/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return resp.json();
  }

  async getMemoryStats(): Promise<Record<string, { ready: boolean; count: number; health: string }>> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/memory/stats`);
      if (!resp.ok) return {};
      return resp.json();
    } catch {
      return {};
    }
  }

  async storeMemory(params: {
    content: string;
    tier: string;
    source?: string;
    tags?: string[];
    confidence?: number;
  }): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/memory/store`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async consolidateMemory(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/memory/consolidate`, {
      method: "POST",
    });
    return resp.json();
  }

  async listEpisodicEvents(limit = 20): Promise<Record<string, unknown>> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/memory/episodic?limit=${limit}`);
      if (!resp.ok) return { events: [] };
      return resp.json();
    } catch {
      return { events: [] };
    }
  }

  // Cognitive workspace
  async getCognitiveState(): Promise<CognitiveState> {
    const resp = await fetch(`${this.baseUrl}/v1/cognitive/state`);
    return resp.json();
  }

  // Document collections (Qdrant)
  async listCollections(): Promise<Array<{ name: string; vectors_count?: number; points_count?: number }>> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/collections`);
      return resp.json();
    } catch {
      return [];
    }
  }

  // Search (hybrid)
  async search(query: string, collection = "default", topK = 10) {
    const resp = await fetch(`${this.baseUrl}/v1/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, collection, top_k: topK, use_hybrid: true }),
    });
    return resp.json();
  }

  // ─── Generation ──────────────────────────────────────────────────────

  async generateImage(params: {
    prompt: string;
    negative_prompt?: string;
    pipeline?: string;
    width?: number;
    height?: number;
    steps?: number;
    cfg?: number;
    seed?: number;
    lora_name?: string;
    lora_strength?: number;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async generateFace(params: {
    prompt: string;
    reference_image: string;
    pipeline?: string;
    identity_strength?: number;
    width?: number;
    height?: number;
    seed?: number;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/face`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async generateQueen(params: {
    queen_id: string;
    mode?: string;
    scene_index?: number;
    prompt_override?: string;
    identity_strength?: number;
    seed?: number;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/queen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  getImageUrl(filename: string, type = "output"): string {
    return `${this.baseUrl}/v1/generate/view?filename=${encodeURIComponent(filename)}&type=${type}`;
  }

  async generationStatus(): Promise<{
    active_service: string;
    queue_running: number;
    queue_pending: number;
  }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/status`);
      return resp.json();
    } catch {
      return { active_service: "offline", queue_running: 0, queue_pending: 0 };
    }
  }

  async generationHistory(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/history`);
    return resp.json();
  }

  async generationQueue(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/queue`);
    return resp.json();
  }

  async listPipelines(): Promise<
    Array<{ id: string; name: string; type: string; est_time: string }>
  > {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/pipelines`);
      return resp.json();
    } catch {
      return [];
    }
  }

  async listQueens(): Promise<QueenProfile[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/queens`);
      return resp.json();
    } catch {
      return [];
    }
  }

  async getQueen(queenId: string): Promise<QueenProfile | null> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/queens/${queenId}`);
      if (!resp.ok) return null;
      return resp.json();
    } catch {
      return null;
    }
  }

  async searchPerformers(params: {
    q?: string;
    min_rating?: number;
    favorites_only?: boolean;
    limit?: number;
  }): Promise<PerformerInfo[]> {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.min_rating) qs.set("min_rating", String(params.min_rating));
    if (params.favorites_only) qs.set("favorites_only", "true");
    if (params.limit) qs.set("limit", String(params.limit));
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/performers?${qs}`);
      return resp.json();
    } catch {
      return [];
    }
  }

  async uploadImage(file: File): Promise<{ name: string; subfolder: string; type: string }> {
    const form = new FormData();
    form.append("image", file);
    const resp = await fetch(`${this.baseUrl}/v1/generate/upload`, {
      method: "POST",
      body: form,
    });
    return resp.json();
  }

  async listGenModels(): Promise<{ checkpoints: string[]; loras: string[] }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/models`);
      return resp.json();
    } catch {
      return { checkpoints: [], loras: [] };
    }
  }

  // ─── Drop Folder (Auto-Gen) ──────────────────────────────────────────

  async listDrops(): Promise<DropsStatus> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/drops`);
      return resp.json();
    } catch {
      return { scanner_running: false, total_drops: 0, pending: 0, processing: 0, done: 0, errors: 0, entries: [] };
    }
  }

  async getDropDetail(name: string): Promise<DropDetail | null> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/drops/${encodeURIComponent(name)}`);
      if (!resp.ok) return null;
      return resp.json();
    } catch {
      return null;
    }
  }

  async processDrop(name: string): Promise<void> {
    await fetch(`${this.baseUrl}/v1/generate/drops/${encodeURIComponent(name)}/process`, { method: "POST" });
  }

  async retryDrop(name: string): Promise<void> {
    await fetch(`${this.baseUrl}/v1/generate/drops/${encodeURIComponent(name)}/retry`, { method: "POST" });
  }

  async scanDrops(): Promise<{ pending: number; names: string[] }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/drops/scan`, { method: "POST" });
    return resp.json();
  }

  getDropImageUrl(name: string, filename: string): string {
    return `${this.baseUrl}/v1/generate/drops/${encodeURIComponent(name)}/image/${encodeURIComponent(filename)}`;
  }

  getDropRefUrl(name: string, filename: string): string {
    return `${this.baseUrl}/v1/generate/drops/${encodeURIComponent(name)}/ref/${encodeURIComponent(filename)}`;
  }

  // ─── Gallery ──────────────────────────────────────────────────────────

  async fetchGallery(): Promise<GalleryResponse> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/gallery`);
      return resp.json();
    } catch {
      return { subjects: [], total_subjects: 0, total_images: 0, ratings: {}, feedback_summary: { total_rated: 0, total_good: 0, total_bad: 0, preferences_active: false } };
    }
  }

  async rateImage(subject: string, filename: string, rating: "good" | "bad", prompt?: string, notes?: string): Promise<void> {
    await fetch(`${this.baseUrl}/v1/generate/feedback/rate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, filename, rating, prompt, notes }),
    });
  }

  // ─── Training ─────────────────────────────────────────────────────────

  async startTraining(params: {
    trigger_word: string;
    model_type?: string;
    dataset_path?: string;
    epochs?: number;
  }): Promise<TrainingJob> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/train`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async getTrainingStatus(jobId: string): Promise<TrainingJob> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/train/${jobId}`);
    return resp.json();
  }

  async listTrainingJobs(): Promise<TrainingJob[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/train`);
      return resp.json();
    } catch {
      return [];
    }
  }

  // ─── Performer Refs ───────────────────────────────────────────────────

  async uploadPerformerRef(performerName: string, file: File): Promise<{
    performer: string;
    slug: string;
    filename: string;
    total_refs: number;
  }> {
    const form = new FormData();
    form.append("performer_name", performerName);
    form.append("file", file);
    const resp = await fetch(`${this.baseUrl}/v1/generate/upload-ref`, {
      method: "POST",
      body: form,
    });
    return resp.json();
  }

  async listPerformerRefs(slug: string): Promise<{ slug: string; images: string[]; count: number }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/generate/performer-refs/${slug}`);
      return resp.json();
    } catch {
      return { slug, images: [], count: 0 };
    }
  }

  getPerformerRefUrl(slug: string, filename: string): string {
    return `${this.baseUrl}/v1/generate/performer-refs/${slug}/${encodeURIComponent(filename)}`;
  }

  // ─── Img2Img & Inpainting ─────────────────────────────────────────────

  async generateImg2Img(params: {
    prompt: string;
    source_image: string;
    negative_prompt?: string;
    pipeline?: string;
    denoise_strength?: number;
    width?: number;
    height?: number;
    steps?: number;
    cfg?: number;
    seed?: number;
    lora_name?: string;
    lora_strength?: number;
    restore_face?: boolean;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/img2img`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async generateInpaint(params: {
    prompt: string;
    source_image: string;
    mask_image: string;
    negative_prompt?: string;
    denoise_strength?: number;
    width?: number;
    height?: number;
    steps?: number;
    cfg?: number;
    seed?: number;
    lora_name?: string;
    lora_strength?: number;
    restore_face?: boolean;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const resp = await fetch(`${this.baseUrl}/v1/generate/inpaint`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  // ─── Prompt Templates ───────────────────────────────────────────────────

  async listTemplates(category?: string): Promise<PromptTemplate[]> {
    try {
      const qs = category ? `?category=${category}` : "";
      const resp = await fetch(`${this.baseUrl}/v1/generate/templates${qs}`);
      return resp.json();
    } catch {
      return [];
    }
  }

  async generateFromTemplate(params: {
    template_id: string;
    subject?: string;
    seed?: number;
    restore_face?: boolean;
  }): Promise<{ prompt_id: string; client_id: string }> {
    const qs = new URLSearchParams();
    qs.set("template_id", params.template_id);
    if (params.subject) qs.set("subject", params.subject);
    if (params.seed !== undefined) qs.set("seed", String(params.seed));
    if (params.restore_face !== undefined) qs.set("restore_face", String(params.restore_face));
    const resp = await fetch(`${this.baseUrl}/v1/generate/from-template?${qs}`, {
      method: "POST",
    });
    return resp.json();
  }

  // ─── Cancel Generation ──────────────────────────────────────────────────

  async cancelGeneration(promptId: string): Promise<void> {
    try {
      await fetch(`${this.baseUrl}/v1/generate/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_id: promptId }),
      });
    } catch {
      // Ignore cancel failures
    }
  }


  // ─── Workspaces ─────────────────────────────────────────────────────

  async listWorkspaces(): Promise<Workspace[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/workspaces`);
      const data = await resp.json();
      return data.workspaces || [];
    } catch {
      return [];
    }
  }

  async getActiveWorkspace(sessionId: string): Promise<Workspace | null> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/workspaces/active/${sessionId}`);
      if (!resp.ok) return null;
      return resp.json();
    } catch {
      return null;
    }
  }

  async setActiveWorkspace(sessionId: string, slug: string): Promise<Workspace | null> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/workspaces/active/${sessionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      if (!resp.ok) return null;
      return resp.json();
    } catch {
      return null;
    }
  }

  // ─── Agents ──────────────────────────────────────────────────────────

  async listAgents(): Promise<{ agents: AgentInfo[]; server_url: string }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents`);
      if (!resp.ok) return { agents: [], server_url: "" };
      return resp.json();
    } catch {
      return { agents: [], server_url: "" };
    }
  }

  async agentServerHealth(): Promise<{ status: string; server: string }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/health`);
      return resp.json();
    } catch {
      return { status: "offline", server: "" };
    }
  }

  async getAgentActivity(limit = 20): Promise<AgentActivity[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/activity?limit=${limit}`);
      if (!resp.ok) return [];
      const data = await resp.json();
      return data.activity || data.entries || [];
    } catch {
      return [];
    }
  }

  async getAgentTrust(): Promise<Record<string, AgentTrust>> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/trust`);
      if (!resp.ok) return {};
      const data = await resp.json();
      return data.agents || {};
    } catch {
      return {};
    }
  }

  async getAgentSchedules(): Promise<AgentSchedule[]> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/schedules`);
      if (!resp.ok) return [];
      const data = await resp.json();
      return data.schedules || data.agents || [];
    } catch {
      return [];
    }
  }

  async submitAgentTask(params: {
    agent: string;
    prompt: string;
    priority?: string;
    stream?: boolean;
  }): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/agents/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async chatWithAgent(
    agentName: string,
    message: string,
  ): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/agents/${agentName}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    return resp.json();
  }

  async submitAgentFeedback(params: {
    agent: string;
    task_id?: string;
    vote: "up" | "down";
    comment?: string;
  }): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/agents/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return resp.json();
  }

  async getAgentWorkplan(): Promise<Record<string, unknown>> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/workplan`);
      if (!resp.ok) return {};
      return resp.json();
    } catch {
      return {};
    }
  }

  async getPendingActions(): Promise<{ actions: Array<Record<string, unknown>> }> {
    try {
      const resp = await fetch(`${this.baseUrl}/v1/agents/pending`);
      if (!resp.ok) return { actions: [] };
      return resp.json();
    } catch {
      return { actions: [] };
    }
  }

  async resolvePendingAction(
    actionId: string,
    decision: { approved: boolean; comment?: string },
  ): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/v1/agents/pending/${actionId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision),
    });
    return resp.json();
  }

  // ─── WebSocket ────────────────────────────────────────────────────────

  connectGenerationWs(clientId: string): WebSocket {
    const wsUrl = this.baseUrl.replace("http://", "ws://").replace("https://", "wss://");
    return new WebSocket(`${wsUrl}/v1/generate/ws?clientId=${clientId}`);
  }
}

// ─── Types ─────────────────────────────────────────────────────────────

export interface QueenDNA {
  dominance: number;
  submission: number;
  exhibitionism: number;
  voyeurism: number;
  nurturing: number;
  corruption: number;
  possessiveness: number;
  devotion: number;
  playfulness: number;
  intensity: number;
  ritualism: number;
  spontaneity: number;
  emotional_openness: number;
  guardedness: number;
  sensory_focus: number;
  intellectual_arousal: number;
  power_exchange: number;
  intimacy_threshold: number;
  taboo_comfort: number;
}

export interface QueenScene {
  title: string;
  description: string;
  flux_prompt: string;
}

export interface QueenProfile {
  id: string;
  name: string;
  performer_ref: string;
  physical_blueprint: Record<string, string>;
  dna: QueenDNA;
  flux_portrait_prompt: string;
  scenes: QueenScene[];
  lora_name: string | null;
  reference_images: string[];
}

export interface PerformerInfo {
  name: string;
  rating: number;
  gen_ready: number;
  height: string | null;
  bust: string | null;
  implants: boolean | null;
  body_type: string | null;
  ethnicity: string | null;
  nationality: string | null;
  is_favorite: boolean;
}

export interface DropEntry {
  name: string;
  image_count: number;
  status: "pending" | "processing" | "done" | "error";
  error?: string;
  created_at: number;
  processed_at?: number;
  refs_created: number;
  images_generated: number;
}

export interface DropsStatus {
  scanner_running: boolean;
  total_drops: number;
  pending: number;
  processing: number;
  done: number;
  errors: number;
  entries: DropEntry[];
}

export interface TrainingJob {
  job_id: string;
  status: "preparing" | "training" | "completed" | "failed";
  progress: number;
  current_epoch: number;
  total_epochs: number;
  eta_seconds: number;
}

export interface PromptTemplate {
  id: string;
  name: string;
  category: string;
  base_prompt: string;
  negative_prompt: string;
  pipeline: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  restore_face: boolean;
  tags: string[];
}

export interface DropDetail extends DropEntry {
  manifest?: {
    name: string;
    source_count: number;
    ref_images: string[];
    generated_images: string[];
    prompt_used: string;
    pipeline: string;
    processed_at: string;
    identity_method: string;
  };
  output_images?: string[];
}

// ─── Gallery Types ──────────────────────────────────────────────────────────

export interface GalleryImage {
  filename: string;
  url: string;
  size_bytes: number;
  created: number;
  pipeline: string;
  identity_method: string;
}

export interface GalleryRef {
  filename: string;
  url: string;
}

export interface GallerySubject {
  name: string;
  status: string;
  image_count: number;
  images: GalleryImage[];
  refs: GalleryRef[];
  prompts: string[];
  context: string;
  pipeline: string;
  identity_method: string;
  processed_at: string;
  latest: number;
}

export interface GalleryResponse {
  subjects: GallerySubject[];
  total_subjects: number;
  total_images: number;
  ratings: Record<string, string>;
  feedback_summary: {
    total_rated: number;
    total_good: number;
    total_bad: number;
    preferences_active: boolean;
  };
}

export const api = new ApiClient(BASE_URL);
