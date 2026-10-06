import test from "node:test";
import assert from "node:assert/strict";
import { chunkDocument, SessionIndex, standaloneQuery } from "../src/rag/retrieval.ts";
import type { SessionDocument } from "../src/rag/retrieval.ts";

function document(id: string, text: string, quality = 0, status = "Unverified"): SessionDocument {
  return { id, text, metadata: { type: "evidence", title: id, sourceId: id, qualityScore: quality, evidenceStatus: status } };
}

test("chunks cover Unicode source text with bounded size and overlap", () => {
  const text = "🧪 A source passage containing research evidence. ".repeat(150);
  const chunks = chunkDocument(document("S1", text));
  const chars = Array.from(text);
  assert.equal(chunks[0].start, 0);
  assert.equal(chunks.at(-1)?.end, chars.length);
  for (let i = 0; i < chunks.length; i++) {
    assert.ok(chunks[i].end - chunks[i].start <= 1600);
    assert.equal(chunks[i].text, chars.slice(chunks[i].start, chunks[i].end).join(""));
    if (i) assert.ok(chunks[i].start < chunks[i - 1].end);
  }
  assert.throws(() => chunkDocument(document("S1", text), 100, 100));
});

test("BM25 retrieves a specific finding deep in source text and returns no unrelated fallback", () => {
  const index = new SessionIndex("active", [document("source:S1", "General introduction. ".repeat(500) + "Quantum widget throughput is limited by photon loss."), document("evidence:E2", "Classical widget latency depends on copper wiring.")]);
  const results = index.retrieve("What limits quantum widget throughput?");
  assert.ok(results[0].text.includes("photon loss"));
  assert.deepEqual(index.retrieve("Unmentioned penguin migration"), []);
});

test("validated evidence and source quality boost equal lexical matches; K is capped", () => {
  const documents = Array.from({ length: 20 }, (_, i) => document(`E${i}`, "Widget efficiency depends on insulation.", i === 19 ? 1 : 0, i === 19 ? "Supported" : "Unverified"));
  const index = new SessionIndex("active", documents);
  assert.equal(index.retrieve("widget efficiency", 100)[0].document_id, "E19");
  assert.equal(index.retrieve("widget efficiency", 100).length, 8);
});

test("the second one resolves to the second item in the preceding answer", () => {
  const query = standaloneQuery("What about the second one?", [
    { role: "user", content: "Compare solar power and wind power." },
    { role: "assistant", content: "1. Solar power depends on sunshine. [1]\n2. Wind power depends on airflow. [2]" },
  ]);
  assert.ok(query.includes("Wind power depends on airflow"));
  assert.ok(!query.includes("Solar power depends on sunshine"));
  const index = new SessionIndex("active", [document("solar", "Solar power depends on sunshine."), document("wind", "Wind power depends on airflow.")]);
  assert.equal(index.retrieve(query)[0].document_id, "wind");
});

test("replacing the active index discards earlier session chunks", () => {
  const old = new SessionIndex("old", [document("old", "Zebra migration")]);
  old.replace([]);
  const active = new SessionIndex("new", [document("new", "Photon emission")]);
  assert.deepEqual(old.retrieve("Zebra"), []);
  assert.deepEqual(active.retrieve("Zebra"), []);
  assert.equal(active.sessionId, "new");
});
