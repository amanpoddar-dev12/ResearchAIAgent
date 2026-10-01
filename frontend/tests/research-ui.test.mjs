import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
async function component(name) {
  const source = await readFile(new URL(`../src/components/${name}.tsx`, import.meta.url), "utf8");
  let { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  });
  for (const dependency of ["react", "react/jsx-runtime"]) {
    outputText = outputText.replaceAll(`from "${dependency}"`, `from "${pathToFileURL(require.resolve(dependency)).href}"`);
  }
  return (await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64")))[name];
}

test("derived graph renders every evidence layer and accessible node controls", async () => {
  const ResearchGraph = await component("ResearchGraph");
  const graph = {
    nodes: [
      { id: "question", type: "question", label: "SYNTHETIC TEST QUESTION" },
      { id: "C1", type: "claim", label: "SYNTHETIC TEST CLAIM", status: "Contradicted" },
      { id: "E1", type: "evidence", label: "SYNTHETIC TEST EXCERPT", status: "contradicts" },
      { id: "S1", type: "source", label: "SYNTHETIC TEST SOURCE" },
      { id: "X1", type: "conflict", label: "SYNTHETIC TEST CONFLICT" },
    ],
    edges: [{ source: "question", target: "C1", type: "investigates" }, { source: "C1", target: "E1", type: "evidence" },
      { source: "E1", target: "S1", type: "retrieved_from" }, { source: "S1", target: "X1", type: "conflicts" }],
  };
  const html = renderToStaticMarkup(React.createElement(ResearchGraph, { graph, sources: [], onPreview() {} }));
  assert.equal((html.match(/role="button"/g) || []).length, 5);
  assert.match(html, /Contradicted/);
  assert.match(html, /S1 → X1: conflicts/);
  assert.match(html, /tabindex="0"/);
  assert.match(html, /SYNTHETIC TEST EXCERPT/);
});

test("audit renders session timestamps, decisions, reasons and search controls", async () => {
  const AuditView = await component("AuditView");
  const html = renderToStaticMarkup(React.createElement(AuditView, { entries: [
    { id: 1, timestamp: "2026-01-01T00:00:00Z", action: "search", message: "SYNTHETIC TEST QUERY", details: { reason: "Q1 has no verified evidence" } },
    { id: 2, timestamp: "2026-01-01T00:00:01Z", action: "stop_decision", message: "search budget exhausted", details: { stop: true } },
  ] }));
  assert.match(html, /datetime="2026-01-01T00:00:00Z"/i);
  assert.match(html, /Q1 has no verified evidence/);
  assert.match(html, /search budget exhausted/);
  assert.match(html, /aria-label="Search audit"/);
  assert.match(html, /2 of 2 session decisions/);
});