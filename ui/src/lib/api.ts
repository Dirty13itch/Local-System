/**
 * API client for the Local-System gateway.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8700";

export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
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

export type ClusterHealth = Record<string, Record<string, unknown>>;

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
          if (data.delta) {
            onChunk(data.delta);
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

  async searchMemory(query: string, topK = 10) {
    const resp = await fetch(`${this.baseUrl}/v1/memory/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: topK }),
    });
    return resp.json();
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
}

export const api = new ApiClient(BASE_URL);
