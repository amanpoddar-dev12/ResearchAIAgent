import type { ResearchEvent, ResearchRequest, ResearchState } from "../types/research";

// Local fetch and SSE requests must use Vite's /api proxy, even when a production URL is configured.
const API_URL = (import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");
const backendHint = API_URL || import.meta.env.VITE_BACKEND_URL || "the configured FastAPI port";

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
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join("; ") : detail || "Could not start research.");
  }
  return (await response.json()).research_id;
}

export function streamResearch(id: string, onEvent: (event: ResearchEvent) => void, onError: (error: Error) => void): () => void {
  const source = new EventSource(`${API_URL}/api/research/${id}/stream`);
  let stopped = false;
  let recovering = false;
  let recoveryController: AbortController | undefined;
  const stop = () => {
    stopped = true;
    source.close();
    recoveryController?.abort();
  };
  const recoverResult = async () => {
    if (stopped || recovering) return;
    recovering = true;
    const controller = new AbortController();
    recoveryController = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      // Older servers can close after research_completed before flushing complete.
      // Retrieve the existing job; never start a second, potentially billable run.
      for (let attempt = 0; attempt < 3 && !stopped; attempt++) {
        const response = await apiRequest(`${API_URL}/api/research/${id}`, { signal: controller.signal });
        if (stopped) return;
        if (response.ok) {
          const state = await response.json() as ResearchState;
          if (stopped) return;
          if (state.status === "complete" && state.final_report) {
            stop();
            onEvent({ type: "complete", message: "Research completed", timestamp: new Date().toISOString(),
              data: { state, report: state.final_report }, progress: 100, phase: "complete", mode: state.mode });
            return;
          }
        } else if (response.status !== 404) {
          break;
        }
        // research_completed may arrive just before the result becomes available.
        if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 300));
      }
    } catch {
      // Cancellation or a normal terminal SSE event must not become an error.
    } finally {
      clearTimeout(timeout);
      recovering = false;
    }
    if (!stopped) {
      stop();
      onError(new Error(`The research connection to ${backendHint} ended before a completed report could be retrieved. Retry the research session.`));
    }
  };
  source.onmessage = (message) => {
    if (stopped) return;
    let event: ResearchEvent;
    try {
      event = JSON.parse(message.data) as ResearchEvent;
    } catch { stop(); onError(new Error("Received malformed research event.")); return; }
    if (["complete", "research_failed"].includes(event.type)) stop();
    onEvent(event);
    if (event.type === "research_completed") void recoverResult();
  };
  source.onerror = () => {
    if (stopped) return;
    source.close();
    void recoverResult();
  };
  return stop;
}
