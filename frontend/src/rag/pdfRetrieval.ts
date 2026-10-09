import { SessionIndex, standaloneQuery } from "./retrieval";
import type { HistoryMessage, SessionDocument } from "./retrieval";
export interface PDFPage { page: number; text: string }
export interface PDFDocument { id: string; name: string; page_count: number; pages: PDFPage[]; warnings: string[]; storage_path?: string }
export interface PDFChunk { page: number; text: string }
export interface PDFContext { document_id: string; name: string; page_count: number; chunks: PDFChunk[] }
export function pdfIndex(pdf: PDFDocument): SessionIndex {
  const documents: SessionDocument[] = pdf.pages.map((page) => ({ id: String(page.page), text: page.text, metadata: { type: "source", title: pdf.name, sourceId: `P${page.page}`, qualityScore: 0, evidenceStatus: "Unverified" } }));
  return new SessionIndex(pdf.id, documents);
}
export function retrievePDF(index: SessionIndex, pdf: PDFDocument, question: string, history: HistoryMessage[]): PDFContext {
  const query = standaloneQuery(question, history);
  const explicitPage = query.match(/\bpage\s+(\d+)\b/i);
  let chunks = index.retrieve(explicitPage ? `${query} @source:P${explicitPage[1]}` : query);
  if (!chunks.length && /summari[sz]e|summary|main (?:findings|points)|overview|document about/i.test(question)) {
    chunks = pdf.pages.slice(0, 8).map((page) => ({ document_id: String(page.page), start: 0, end: 1600, text: page.text.slice(0,1600), metadata: { type: "source" as const, title: pdf.name, qualityScore: 0, evidenceStatus: "Unverified" } }));
  }
  return { document_id: pdf.id, name: pdf.name, page_count: pdf.page_count, chunks: chunks.slice(0,8).map((chunk) => ({ page: Number(chunk.document_id), text: chunk.text })) };
}
