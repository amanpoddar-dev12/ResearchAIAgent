import { pdfIndex, retrievePDF } from "./pdfRetrieval";
import type { PDFDocument } from "./pdfRetrieval";
import type { HistoryMessage, SessionIndex } from "./retrieval";
let document: PDFDocument;
let index: SessionIndex;
self.onmessage = (event: MessageEvent<{ type: string; requestId?: number; document?: PDFDocument; question?: string; history?: HistoryMessage[] }>) => {
  try {
    if (event.data.type === "index" && event.data.document) { document = event.data.document; index = pdfIndex(document); self.postMessage({ type: "ready" }); }
    else if (event.data.type === "retrieve" && index) self.postMessage({ type: "retrieved", requestId: event.data.requestId, context: retrievePDF(index, document, event.data.question || "", event.data.history || []) });
  } catch { self.postMessage({ type: "error", requestId: event.data.requestId, error: "The PDF index could not be prepared. Try a smaller document." }); }
};
