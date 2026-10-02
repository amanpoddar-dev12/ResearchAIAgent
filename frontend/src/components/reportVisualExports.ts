import type { ChartSpec, ResearchSource } from "../types/research";

export const chartColors = ["#4f46e5", "#0f766e", "#d97706", "#be123c", "#7c3aed", "#0891b2"];
const finiteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Keep missing measurements missing; never turn null or numeric-looking text into zero. */
export function chartRows(chart: ChartSpec) {
  return chart.data.filter((row) => {
    const x = row[chart.x_key];
    return chart.type === "scatter" ? finiteNumber(x) : x !== null && x !== undefined && String(x).trim() !== "";
  }).map((row) => {
    const result = { ...row };
    for (const series of chart.series) {
      const value = row[series.key];
      result[series.key] = finiteNumber(value) && (chart.type !== "pie" || value >= 0) ? value : null;
    }
    return result;
  });
}

export function chartCsv(chart: ChartSpec, rows = chartRows(chart)) {
  const columns = [...new Set([chart.x_key, ...chart.series.map((series) => series.key)])];
  const cell = (value: string | number | null | undefined) => {
    let text = value === null || value === undefined ? "" : String(value);
    // Text labels remain text when a downloaded CSV is opened in a spreadsheet.
    if (typeof value === "string" && /^[=+@\-\t\r]/.test(text)) text = "'" + text;
    return `"${text.replace(/"/g, '""')}"`;
  };
  return [columns.map(cell).join(","), ...rows.map((row) => columns.map((column) => cell(row[column])).join(","))].join("\r\n");
}

export function chartLegend(chart: ChartSpec, rows = chartRows(chart)) {
  return chart.type === "pie"
    ? rows.filter((row) => finiteNumber(row[chart.series[0]?.key])).map((row, index) => ({ label: String(row[chart.x_key]), color: chartColors[index % chartColors.length] }))
    : chart.series.map((series, index) => ({ label: series.label, color: series.color || chartColors[index % chartColors.length] }));
}

function backgroundColor(element: Element) {
  for (let node: Element | null = element; node; node = node.parentElement) {
    const color = getComputedStyle(node).backgroundColor;
    if (color && color !== "transparent" && color !== "rgba(0, 0, 0, 0)") return color;
  }
  return "#ffffff";
}

/** Preserve the actual Recharts surface and the styles it inherits from the page. */
export function serializeChartSvg(surface: SVGSVGElement, chart: ChartSpec, sources: ResearchSource[]) {
  const rect = surface.getBoundingClientRect();
  const plotWidth = rect.width || surface.viewBox.baseVal.width;
  const plotHeight = rect.height || surface.viewBox.baseVal.height;
  if (!plotWidth || !plotHeight) throw new Error("The chart is not ready yet. Try again when it is visible.");
  const clone = surface.cloneNode(true) as SVGSVGElement;
  const originals = [surface, ...surface.querySelectorAll("*")];
  const copies = [clone, ...clone.querySelectorAll("*")];
  const properties = ["fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline"];
  originals.forEach((node, index) => {
    const style = getComputedStyle(node);
    const target = copies[index] as SVGElement;
    for (const property of properties) {
      const value = style.getPropertyValue(property);
      if (value) target.style.setProperty(property, value);
    }
  });
  const ns = "http://www.w3.org/2000/svg";
  const output = document.createElementNS(ns, "svg");
  const width = Math.max(360, Math.ceil(plotWidth + 48));
  const foreground = getComputedStyle(surface).color || "#0f172a";
  const background = document.createElementNS(ns, "rect");
  background.setAttribute("width", "100%"); background.setAttribute("height", "100%");
  background.setAttribute("fill", backgroundColor(surface)); output.append(background);
  let y = 28;
  const line = (text: string, size: number, bold = false, inset = 24) => {
    const maxCharacters = Math.max(20, Math.floor((width - inset - 24) / (size * 0.57)));
    const lines = text.match(new RegExp(`.{1,${maxCharacters}}(?:\\s|$)|.{1,${maxCharacters}}`, "g")) || [""];
    for (const wordsOnLine of lines) {
      const node = document.createElementNS(ns, "text");
      node.setAttribute("x", String(inset)); node.setAttribute("y", String(y));
      node.setAttribute("fill", foreground); node.setAttribute("font-family", "Arial, sans-serif");
      node.setAttribute("font-size", String(size)); node.setAttribute("font-weight", bold ? "600" : "400");
      node.textContent = wordsOnLine.trim(); output.append(node); y += size * 1.5;
    }
  };
  line(chart.title, 18, true); y += 4;
  line(chart.caption, 12); y += 12;
  clone.setAttribute("x", "24"); clone.setAttribute("y", String(y));
  clone.setAttribute("width", String(plotWidth)); clone.setAttribute("height", String(plotHeight));
  output.append(clone); y += plotHeight + 22;
  for (const item of chartLegend(chart)) {
    const key = document.createElementNS(ns, "rect");
    key.setAttribute("x", "24"); key.setAttribute("y", String(y - 9));
    key.setAttribute("width", "10"); key.setAttribute("height", "10"); key.setAttribute("fill", item.color);
    output.append(key); line(item.label, 11, false, 42);
  }
  y += 10;
  for (const id of [...new Set(chart.source_ids)]) {
    const index = sources.findIndex((source) => source.id === id);
    if (index !== -1) line(`[${index + 1}] ${sources[index].title} — ${sources[index].url}`, 10);
  }
  const height = Math.ceil(y + 16);
  output.setAttribute("xmlns", ns); output.setAttribute("width", String(width)); output.setAttribute("height", String(height));
  output.setAttribute("viewBox", `0 0 ${width} ${height}`);
  return { content: new XMLSerializer().serializeToString(output), width, height };
}

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename;
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function chartPng(svg: ReturnType<typeof serializeChartSvg>): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg.content], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("The chart image could not be rendered. Try the SVG download."));
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = svg.width * 2; canvas.height = svg.height * 2;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("PNG export is not available in this browser. Try SVG.");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG export failed. Try SVG.")), "image/png"));
  } finally { URL.revokeObjectURL(url); }
}
