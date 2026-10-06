export type DocumentType = "session" | "source" | "claim" | "evidence" | "validation" | "rejection" | "report" | "gap" | "conflict";
export interface ChunkMetadata { type: DocumentType; sourceId?: string | null; url?: string | null; title: string; claimId?: string | null; evidenceId?: string | null; evidenceIds?: string[]; qualityScore: number; evidenceStatus: string }
export interface SessionDocument { id: string; text: string; metadata: ChunkMetadata }
export interface ChunkReference { document_id: string; start: number; end: number }
export interface Chunk extends ChunkReference { text: string; metadata: ChunkMetadata }
export interface HistoryMessage { role: "user" | "assistant"; content: string }
export interface RetrievalSelection { session_id: string; query: string; chunks: ChunkReference[] }

const stopwords = new Set("a an and are as at be by can do does for from how i in is it me of on or please research say show tell that the their these this to was were what which with you your about explain simple terms findings finding one second first third".split(" "));
export function tokens(text: string): string[] {
  return (text.toLowerCase().match(/[\p{L}\p{N}_]+/gu) || []).filter((term) => term.length > 1 && !stopwords.has(term));
}

// Offsets count Unicode code points, matching Python slicing on the server.
export function chunkDocument(document: SessionDocument, size = 1600, overlap = 160): Chunk[] {
  if (size < 1 || overlap < 0 || overlap >= size) throw new Error("Invalid chunk bounds");
  const chars = Array.from(document.text);
  const chunks: Chunk[] = [];
  for (let start = 0; start < chars.length;) {
    let end = Math.min(chars.length, start + size);
    if (end < chars.length) {
      const boundary = chars.slice(start + Math.floor(size * 0.8), end).lastIndexOf(" ");
      if (boundary >= 0) end = start + Math.floor(size * 0.8) + boundary;
    }
    chunks.push({ document_id: document.id, start, end, text: chars.slice(start, end).join(""), metadata: document.metadata });
    if (end === chars.length) break;
    start = Math.max(start + 1, end - overlap);
  }
  return chunks;
}

export function standaloneQuery(question: string, history: HistoryMessage[]): string {
  const prior = history.slice(-6);
  const ordinal = question.match(/\b(first|second|third|fourth)\s+(?:one|finding|claim|source|option)\b/i);
  const assistant = [...prior].reverse().find((item) => item.role === "assistant");
  if (ordinal && assistant) {
    const numbered = assistant.content.split(/\n/).filter((line) => /^\s*(?:\d+[.)]|[-*])\s+/.test(line));
    const items = numbered.length ? numbered : assistant.content.split(/\n\s*\n/).filter(Boolean);
    const index = ["first", "second", "third", "fourth"].indexOf(ordinal[1].toLowerCase());
    if (items[index]) return `${question} Regarding: ${items[index]}`.slice(0, 4000);
  }
  if (/\b(it|they|them|those|that|this|ones?)\b/i.test(question) || tokens(question).length < 2) {
    const user = [...prior].reverse().find((item) => item.role === "user");
    return `${question}\nPrevious question: ${user?.content || ""}\nPrevious answer: ${assistant?.content || ""}`.slice(0, 4000);
  }
  return question;
}

export class SessionIndex {
  readonly sessionId: string;
  private chunks: Chunk[] = [];
  private frequencies: Map<string, number>[] = [];
  private documentFrequency = new Map<string, number>();
  private averageLength = 1;

  constructor(sessionId: string, documents: SessionDocument[]) {
    this.sessionId = sessionId;
    this.replace(documents);
  }

  replace(documents: SessionDocument[]): void {
    this.chunks = documents.flatMap((document) => chunkDocument(document));
    this.documentFrequency = new Map();
    let length = 0;
    this.frequencies = this.chunks.map((chunk) => {
      const words = tokens(chunk.text + " " + chunk.metadata.title);
      length += words.length;
      const frequency = new Map<string, number>();
      words.forEach((term) => frequency.set(term, (frequency.get(term) || 0) + 1));
      frequency.forEach((_, term) => this.documentFrequency.set(term, (this.documentFrequency.get(term) || 0) + 1));
      return frequency;
    });
    this.averageLength = length / Math.max(1, this.chunks.length) || 1;
  }

  retrieve(query: string, k = 8): Chunk[] {
    const terms = [...new Set(tokens(query))];
    const ranked = this.chunks.map((chunk, index) => {
      const frequency = this.frequencies[index];
      const length = [...frequency.values()].reduce((sum, count) => sum + count, 0);
      let score = 0;
      for (const term of terms) {
        const count = frequency.get(term) || 0;
        const df = this.documentFrequency.get(term) || 0;
        const idf = Math.log(1 + (this.chunks.length - df + 0.5) / (df + 0.5));
        score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / this.averageLength));
      }
      const explicit = query.match(/@(claim|finding|source|evidence):([\w.-]+)/gi) || [];
      if (explicit.some((ref) => {
        const [kind, id] = ref.slice(1).split(":");
        return kind === "source" ? chunk.metadata.sourceId === id : kind === "evidence" ? chunk.metadata.evidenceId === id : chunk.metadata.claimId === id;
      })) score += 20;
      score *= 1 + 0.3 * Math.max(0, Math.min(1, chunk.metadata.qualityScore || 0)) + (chunk.metadata.evidenceStatus === "Supported" ? 0.25 : 0);
      return { chunk, score };
    }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
    const selected: Chunk[] = [];
    for (const { chunk } of ranked) {
      if (selected.some((old) => old.document_id === chunk.document_id && old.start < chunk.end && chunk.start < old.end)) continue;
      selected.push(chunk);
      if (selected.length >= Math.max(1, Math.min(8, k))) break;
    }
    return selected;
  }
}
