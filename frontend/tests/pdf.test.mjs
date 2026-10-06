import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "../node_modules/typescript/lib/typescript.js";
function moduleURL(path, replacement = null) {
  let source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
  if (replacement) source = source.replaceAll('"./retrieval"', JSON.stringify(replacement));
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
  return `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
}
const retrievalURL = moduleURL("../src/rag/retrieval.ts");
const { pdfIndex, retrievePDF } = await import(moduleURL("../src/rag/pdfRetrieval.ts", retrievalURL));
test("large PDF retrieval finds a late-page detail and sends at most eight chunks", () => {
  const pdf = { id: "large", name: "report.pdf", page_count: 1000, warnings: [], pages: Array.from({ length: 1000 }, (_, i) => ({ page: i+1, text: i === 998 ? "Quantum widget throughput is 42 units per hour." : "Ordinary introductory background. ".repeat(100) })) };
  const index = pdfIndex(pdf);
  const context = retrievePDF(index, pdf, "What is quantum widget throughput?", []);
  assert.equal(context.chunks[0].page, 999);
  assert.ok(context.chunks[0].text.includes("42 units"));
  assert.ok(context.chunks.length <= 8);
  assert.ok(context.chunks.every((chunk) => Array.from(chunk.text).length <= 1600));
  assert.deepEqual(retrievePDF(index, pdf, "Unmentioned penguin migration", []).chunks, []);
  assert.equal(retrievePDF(index, pdf, "Explain page 999", []).chunks[0].page, 999);
});
test("PDF follow-ups resolve from chat history and summaries have bounded scope", () => {
  const pdf = { id: "small", name: "report.pdf", page_count: 2, warnings: [], pages: [{page:1,text:"Alpha widgets cost 10 units."},{page:2,text:"Beta widgets cost 20 units."}] };
  const index = pdfIndex(pdf);
  const context = retrievePDF(index, pdf, "What about the second one?", [{role:"assistant",content:"1. Alpha widgets\n2. Beta widgets"}]);
  assert.equal(context.chunks[0].page, 2);
  assert.equal(retrievePDF(index, pdf, "Summarize this document", []).chunks.length, 2);
});
