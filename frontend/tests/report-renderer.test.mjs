import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Vite's existing compiler bundles tests in memory, without writing build artifacts.
const require = createRequire(import.meta.url);
const built = await build({ entryPoints: [fileURLToPath(new URL("../src/components/ResearchReport.tsx", import.meta.url))], bundle: true, write: false, platform: "node", format: "cjs", jsx: "automatic", external: ["react", "react-dom", "react/jsx-runtime"], logLevel: "silent" });
const module = { exports: {} };
new Function("require", "module", "exports", built.outputFiles[0].text)(require, module, module.exports);
const { ResearchReport, splitReport } = module.exports;
const sections = [
  ["abstract", "Title and Abstract"], ["executive-summary", "Executive Summary"], ["introduction", "Introduction and Research Questions"],
  ["methodology", "Methodology"], ["background", "Literature / Background Review"], ["analysis", "Detailed Analysis"],
  ["timeline", "Year-by-Year Progress / Timeline"], ["comparison", "Comparative Analysis"], ["discussion", "Discussion"],
  ["conclusion", "Conclusion and Future Directions"], ["references", "References"],
].map(([id, title]) => ({ id, title, content: "SYNTHETIC TEST ONLY: Widget trial evidence [S1]." }));
const sources = [{ id: "S1", title: "SYNTHETIC TEST ONLY", domain: "example.test", url: "https://example.test/fixture" }];
const chart = { id: "synthetic-trials", type: "bar", title: "SYNTHETIC trial count", caption: "Fictional fixture: not real research.", x_key: "year", series: [{ key: "trials", label: "Trials" }], data: [{ year: 2024, trials: 10 }, { year: 2026, trials: 15 }], source_ids: ["S1"], section_id: "timeline", origin: "retrieved" };
const table = { id: "synthetic-timeline", title: "SYNTHETIC timeline table", caption: "Fictional fixture: not real research.", columns: ["Year", "Trials"], rows: [{ Year: 2024, Trials: 10 }], source_ids: ["S1"], section_id: "timeline" };

test("eleven continuous sections have matching TOC, citations and inline figures", () => {
  const html = renderToStaticMarkup(React.createElement(ResearchReport, { markdown: "# Legacy summary\n## Wrong legacy heading\nOld text", sources, onPreview() {}, structured: { title: "SYNTHETIC ACADEMIC REPORT", sections, charts: [chart, { ...chart, id: "synthetic-comparison", section_id: "comparison" }], tables: [table] } }));
  assert.equal((html.match(/class="report-document-section"/g) || []).length, 11);
  assert.equal((html.match(/href="#report-/g) || []).length, 11);
  assert.ok(!html.includes("Wrong legacy heading"));
  assert.match(html, /Preview source 1/);
  assert.match(html, /SYNTHETIC timeline table/);
  assert.equal((html.match(/<figure/g) || []).length, 3);
  const article = html.slice(html.indexOf("<article"), html.indexOf("</article>"));
  assert.doesNotMatch(article, /class="[^"]*\bcard\b/);
  assert.ok(article.indexOf("SYNTHETIC timeline table") > article.indexOf('id="report-timeline"'));
  assert.ok(article.indexOf("SYNTHETIC timeline table") < article.indexOf('id="report-comparison"'));
  assert.match(html, /report-table-wrap/);
});

test("legacy reports preserve readable content and grouped citations", () => {
  const markdown = "# SYNTHETIC legacy report\n## Executive Summary\nSynthetic citation [1, S1].\n## Evidence\n| Test | Value |\n| --- | --- |\n| Synthetic | 10 |\n";
  const parsed = splitReport(markdown);
  assert.equal(parsed.sections.length, 2);
  assert.equal(parsed.title, "SYNTHETIC legacy report");
  const html = renderToStaticMarkup(React.createElement(ResearchReport, { markdown, sources, onPreview() {} }));
  assert.match(html, /Executive Summary/);
  assert.match(html, /aria-label="Evidence table"/);
  assert.equal((html.match(/Preview source 1/g) || []).length, 2);
});

test("unresolved inline citations are visibly unavailable", () => {
  const html = renderToStaticMarkup(React.createElement(ResearchReport, { markdown: "# SYNTHETIC\n## Evidence\nUnknown [S404].", sources, onPreview() {} }));
  assert.match(html, /citation unavailable/);
  assert.doesNotMatch(html, /Preview source 404/);
});
