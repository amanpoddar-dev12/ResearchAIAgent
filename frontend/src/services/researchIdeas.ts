const topics = ["AI agents and software reliability", "battery storage and renewable grids", "climate adaptation and urban heat", "AI-assisted medical diagnosis", "semiconductor efficiency", "water recycling and scarcity", "robotics in manufacturing", "online misinformation detection", "low-carbon building materials", "data privacy in AI systems"];
const angles = ["What does recent evidence show about", "What are the benefits and limitations of", "Which open research questions remain about", "How do current approaches compare for"];
export function freshResearchIdeas(): string[] {
  const period = new Date().toLocaleDateString("en", { month: "long", year: "numeric" });
  return randomIdeas(topics, 6).map((topic) => `${angles[Math.floor(Math.random() * angles.length)]} ${topic} as of ${period}?`);
}
export function randomIdeas(ideas: string[], count = 3): string[] {
  const pool = [...new Set(ideas)];
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  return pool.slice(0, count);
}
let pending: Promise<string[]> | undefined;
export function loadResearchIdeas(): Promise<string[]> {
  if (pending) return pending;
  pending = (async () => {
    try {
      const cached = JSON.parse(localStorage.getItem("research-ideas-cache") || "null");
      if (cached && cached.expires > Date.now() && Array.isArray(cached.ideas) && cached.ideas.every((idea: unknown) => typeof idea === "string")) return cached.ideas as string[];
    } catch { /* Browser storage is optional for suggestions. */ }
    try {
      const api = (import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");
      const response = await fetch(`${api}/api/assistant/research-ideas`, { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("Ideas unavailable");
      const data = await response.json() as { ideas?: unknown[] };
      const ideas = data.ideas?.filter((idea): idea is string => typeof idea === "string" && idea.length < 250) || [];
      if (ideas.length < 3) return freshResearchIdeas();
      try { localStorage.setItem("research-ideas-cache", JSON.stringify({ ideas, expires: Date.now() + 6 * 3600000 })); } catch { /* Optional cache. */ }
      return ideas;
    } catch { return freshResearchIdeas(); }
  })();
  return pending;
}
