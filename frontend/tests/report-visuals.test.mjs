import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const moduleUrl = (source) => "data:text/javascript;base64," + Buffer.from(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText).toString("base64");
const exportSource = await readFile(new URL("../src/components/reportVisualExports.ts", import.meta.url), "utf8");
const exportUrl = moduleUrl(exportSource);
const { chartRows, chartCsv, serializeChartSvg, chartPng } = await import(exportUrl);
let componentSource = await readFile(new URL("../src/components/ReportVisuals.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(componentSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
for (const dependency of ["react", "react/jsx-runtime", "lucide-react", "recharts"]) {
  compiled = compiled.replaceAll(`from "${dependency}"`, `from "${pathToFileURL(require.resolve(dependency)).href}"`);
}
compiled = compiled.replace('from "./reportVisualExports"', `from "${exportUrl}"`);
const { ReportVisuals } = await import("data:text/javascript;base64," + Buffer.from(compiled).toString("base64"));
const sources = [{ id: "S99", title: "SYNTHETIC TEST SOURCE", url: "https://synthetic.test/measurements", domain: "synthetic.test" }];
const chart = {
  id: "synthetic-chart", type: "line", title: "SYNTHETIC TEST CHART", caption: "SYNTHETIC FIXTURE, not real research.",
  x_key: "year", series: [{ key: "value", label: "Synthetic units" }],
  data: [{ year: 2020, value: 0 }, { year: 2021, value: null }, { year: 2022, value: -2 }], source_ids: ["S99"],
};

test("chart values preserve zeros and gaps and reject nonnumeric or nonfinite measurements", () => {
  const rows = chartRows({ ...chart, data: [...chart.data, { year: 2023, value: "7" }, { year: 2024, value: Infinity }, { year: null, value: 3 }] });
  assert.deepEqual(rows.map((row) => row.value), [0, null, -2, null, null]);
  assert.equal(chart.data[1].value, null);
  assert.deepEqual(chartRows({ ...chart, type: "scatter", data: [{ year: "2020", value: 2 }, { year: 2020, value: 2 }] }), [{ year: 2020, value: 2 }]);
  assert.equal(chartRows({ ...chart, type: "pie" })[2].value, null);
});

test("CSV exports reported data without invented zeros and escapes text/formulas", () => {
  assert.equal(chartCsv(chart), '"year","value"\r\n"2020","0"\r\n"2021",""\r\n"2022","-2"');
  const data = [{ year: '=HYPERLINK("https://synthetic.invalid")', value: -5 }, { year: 'Synthetic, "label"', value: 1 }];
  const csv = chartCsv({ ...chart, data });
  assert.match(csv, /"'=HYPERLINK\(""https:\/\/synthetic.invalid""\)","-5"/);
  assert.match(csv, /"Synthetic, ""label""","1"/);
});

test("figures expose captions, reference numbering, data tables and all three exports without cards", () => {
  const html = renderToStaticMarkup(React.createElement(ReportVisuals, {
    charts: [chart], tables: [{ id: "synthetic-table", title: "SYNTHETIC TABLE", caption: "Synthetic caption", columns: ["year", "value"], rows: chart.data, source_ids: ["S99"] }], sources, onPreview() {},
  }));
  assert.match(html, /SYNTHETIC TEST CHART/);
  assert.match(html, /SYNTHETIC FIXTURE, not real research/);
  assert.match(html, /Preview reference 1: SYNTHETIC TEST SOURCE/);
  assert.match(html, /\[1\]/);
  for (const format of ["PNG", "SVG", "CSV"]) assert.match(html, new RegExp(`>${format}</button>`));
  assert.match(html, /View chart data/);
  assert.match(html, /Not reported/);
  assert.match(html, /role="region" aria-label="SYNTHETIC TABLE table"/);
  assert.doesNotMatch(html, /class="[^"]*\bcard\b/);
  assert.match(componentSource, /querySelector<SVGSVGElement>\("svg\.recharts-surface"\)/);
  assert.match(componentSource, /connectNulls=\{false\}/);
});

test("charts with absent measurements or unresolved citations are honestly withheld", () => {
  for (const invalid of [{ ...chart, data: [{ year: 2020, value: null }] }, { ...chart, source_ids: ["S404"] }]) {
    const html = renderToStaticMarkup(React.createElement(ReportVisuals, { charts: [invalid], tables: [], sources, onPreview() {} }));
    assert.match(html, /This chart is unavailable/);
    assert.doesNotMatch(html, /Download/);
  }
});

class FakeSvgElement {
  constructor(tag) { this.tag = tag; this.attributes = {}; this.children = []; this.textContent = ""; this.styles = {}; this.style = { setProperty: (key, value) => { this.styles[key] = value; } }; }
  setAttribute(key, value) { this.attributes[key] = value; }
  append(child) { child.parentElement = this; this.children.push(child); }
  querySelectorAll() { return this.children.flatMap((child) => [child, ...child.querySelectorAll()]); }
  cloneNode() { const clone = new FakeSvgElement(this.tag); clone.attributes = { ...this.attributes }; clone.textContent = this.textContent; for (const child of this.children) clone.append(child.cloneNode()); return clone; }
  getBoundingClientRect() { return { width: 600, height: 320 }; }
}

test("SVG export contains chart surface, inherited styles, caption, legend and source references", (t) => {
  let serialized;
  t.mock.method(globalThis, "getComputedStyle", () => ({ color: "#112233", backgroundColor: "#ffffff", getPropertyValue: (name) => name === "stroke" ? "#4f46e5" : name === "font-size" ? "11px" : "" }), { create: true });
  t.mock.method(globalThis, "document", { createElementNS: (_, tag) => new FakeSvgElement(tag) }, { create: true });
  t.mock.method(globalThis, "XMLSerializer", class { serializeToString(node) { serialized = node; return "<svg>synthetic</svg>"; } }, { create: true });
  const surface = new FakeSvgElement("svg"); surface.append(new FakeSvgElement("path"));
  const result = serializeChartSvg(surface, chart, sources);
  assert.equal(result.width, 648); assert.ok(result.height > 320);
  const all = [serialized, ...serialized.querySelectorAll()];
  const text = all.map((node) => node.textContent).join(" ");
  assert.match(text, /SYNTHETIC TEST CHART/); assert.match(text, /SYNTHETIC FIXTURE/);
  assert.match(text, /Synthetic units/); assert.match(text, /\[1\] SYNTHETIC TEST SOURCE/);
  assert.match(text, /https:\/\/synthetic.test\/measurements/);
  assert.equal(all.find((node) => node.tag === "path").styles.stroke, "#4f46e5");
});

test("PNG uses the same serialized SVG at double resolution and releases its URL", async (t) => {
  let drawn, released, payload;
  const png = new Blob(["synthetic png"], { type: "image/png" });
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: (...args) => { drawn = args; } }), toBlob: (callback) => callback(png) };
  t.mock.method(globalThis, "document", { createElement: () => canvas }, { create: true });
  t.mock.method(globalThis, "Image", class { set src(value) { this.url = value; queueMicrotask(() => this.onload()); } }, { create: true });
  t.mock.method(URL, "createObjectURL", (blob) => { payload = blob; return "blob:synthetic"; });
  t.mock.method(URL, "revokeObjectURL", (url) => { released = url; });
  assert.equal(await chartPng({ content: "<svg>SYNTHETIC</svg>", width: 600, height: 400 }), png);
  assert.equal(await payload.text(), "<svg>SYNTHETIC</svg>");
  assert.deepEqual([canvas.width, canvas.height, drawn[3], drawn[4]], [1200, 800, 1200, 800]);
  assert.equal(released, "blob:synthetic");
});
