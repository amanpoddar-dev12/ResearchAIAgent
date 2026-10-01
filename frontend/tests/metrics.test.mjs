import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/scoring/metrics.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
});
const metrics = await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

test("missing source quality signals return Not available metadata", () => {
  const result = metrics.relevantSources([{ id: "S1", title: "Source", url: "https://example.test", domain: "example.test" }]);
  assert.equal(result.value, null);
  assert.match(result.formula, /Not available/);
});

test("source and claim metrics expose their contributing factors", () => {
  const sources = [
    { id: "S1", title: "A", url: "https://a.test", domain: "a.test", quality: { relevance: 0.8, authority: 0.8, freshness: 0.8, source_type: 0.8, evidence_strength: 0.8, total: 0.8, notes: [] } },
    { id: "S2", title: "B", url: "https://b.test", domain: "b.test", quality: { relevance: 0.2, authority: 0.4, freshness: 0.4, source_type: 0.4, evidence_strength: 0.4, total: 0.4, notes: [] } },
  ];
  assert.equal(metrics.relevantSources(sources).value, 1);
  assert.equal(metrics.highQualitySources(sources).value, 1);
  assert.ok(metrics.highQualitySources(sources).factors.length > 0);
});

test("coverage remains unavailable without a backend stop decision", () => {
  const result = metrics.researchCoverage({ findings: [], stop_decisions: [] });
  assert.equal(result.value, null);
});
