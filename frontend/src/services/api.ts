import type { ChatResponse, ResearchEvent, ResearchRequest, ResearchState } from "../types/research";
import type { HistoryMessage, RetrievalSelection, SessionDocument } from "../rag/retrieval";

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

export async function askResearch(id: string, message: string, context: { claim_ids?: string[]; finding_ids?: string[]; evidence_ids?: string[]; source_ids?: string[] } = {}, history: { role: "user" | "assistant"; content: string }[] = []): Promise<ChatResponse> {
  const response = await apiRequest(`${API_URL}/api/research/${id}/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, context, history }),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail;
    throw new Error(detail || "The research assistant is temporarily unavailable.");
  }
  return await response.json() as ChatResponse;
}

export async function getChatDocuments(id: string, signal?: AbortSignal): Promise<SessionDocument[]> {
  const response = await apiRequest(`${API_URL}/api/research/${id}/chat/index`, { signal });
  if (!response.ok) throw new Error("The active research session is unavailable. Its index could not be loaded.");
  const payload = await response.json() as { research_id: string; documents: SessionDocument[] };
  if (payload.research_id !== id) throw new Error("Research session mismatch.");
  return payload.documents;
}

export async function streamResearchChat(id: string, message: string, retrieval: RetrievalSelection, history: HistoryMessage[],
  onEvent: (event: ResearchEvent) => void, signal: AbortSignal): Promise<void> {
  const response = await apiRequest(`${API_URL}/api/research/${id}/chat/stream`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, retrieval, history: history.slice(-20) }), signal,
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "The research assistant is unavailable.");
  if (!response.body) throw new Error("The answer stream is unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  try {
    while (!completed) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as ResearchEvent;
        if (event.research_id !== id) throw new Error("Answer stream session mismatch.");
        if (event.type === "chat_error") throw new Error(event.message);
        onEvent(event);
        if (event.type === "chat_complete") completed = true;
      }
      if (done) break;
    }
    if (!completed && !signal.aborted) throw new Error("The answer stream ended before completion. Please retry.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function streamResearch(id: string, onEvent: (event: ResearchEvent) => void, onError: (error: Error) => void): () => void {
  let source: EventSource;
  let sequence = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let connectionFailures = 0;
  let stopped = false;
  let recovering = false;
  let recoveryController: AbortController | undefined;
  const stop = () => {
    stopped = true;
    source.close();
    clearTimeout(reconnectTimer);
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
        const statusResponse = await apiRequest(`${API_URL}/api/research/${id}/status`, { signal: controller.signal });
        if (stopped) return;
        if (statusResponse.ok) {
          const status = await statusResponse.json() as { status: string; error?: string };
          if (stopped) return;
          if (status.status === "running") {
            reconnectTimer = setTimeout(connect, 1000);
            return;
          }
          if (status.status === "failed") {
            stop();
            onError(new Error(status.error || "The research session failed."));
            return;
          }
        }
        // research_completed may arrive just before the result becomes available.
        if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 300));
      }
    } catch {
      // Cancellation or a normal terminal SSE event must not become an error.
      if (!stopped && ++connectionFailures <= 5) {
        reconnectTimer = setTimeout(connect, Math.min(8000, 1000 * 2 ** connectionFailures));
        return;
      }
    } finally {
      clearTimeout(timeout);
      recovering = false;
    }
    if (!stopped) {
      stop();
      onError(new Error(`The research connection to ${backendHint} ended before a completed report could be retrieved. Retry the research session.`));
    }
  };
  const connect = () => {
    if (stopped) return;
    source = new EventSource(`${API_URL}/api/research/${id}/stream${sequence ? `?after=${sequence}` : ""}`);
    source.onmessage = (message) => {
      if (stopped) return;
      let event: ResearchEvent;
      try {
        event = JSON.parse(message.data) as ResearchEvent;
      } catch { stop(); onError(new Error("Received malformed research event.")); return; }
      sequence = Math.max(sequence, event.sequence || 0);
      connectionFailures = 0;
      if (["complete", "research_failed"].includes(event.type)) stop();
      onEvent(event);
      if (event.type === "research_completed") void recoverResult();
    };
    source.onerror = () => {
      if (stopped) return;
      source.close();
      void recoverResult();
    };
  };
  connect();
  return stop;
}

export async function cancelResearch(id: string): Promise<void> {
  const response = await apiRequest(`${API_URL}/api/research/${id}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error("The research session could not be cancelled.");
}
