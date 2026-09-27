import type { ResearchEvent, ResearchRequest } from "../types/research";

const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const backendHint = import.meta.env.VITE_BACKEND_URL || "the configured FastAPI port";

async function apiRequest(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error(
      `The research backend is not reachable at ${backendHint}. Start FastAPI on the configured backend port and retry.`,
    );
  }
}

export async function startResearch(payload: ResearchRequest): Promise<string> {
  const response = await apiRequest(`${API_URL}/api/research`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "Could not start research.");
  return (await response.json()).research_id;
}

export function streamResearch(id: string, onEvent: (event: ResearchEvent) => void, onError: (error: Error) => void): () => void {
  const source = new EventSource(`${API_URL}/api/research/${id}/stream`);
  source.onmessage = (message) => {
    try { onEvent(JSON.parse(message.data) as ResearchEvent); } catch { onError(new Error("Received malformed research event.")); }
  };
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      onError(new Error(`The research backend at ${backendHint} is unavailable. Check VITE_BACKEND_URL and restart Vite.`));
    }
  };
  return () => source.close();
}
