import { useRef, useState } from "react";
import { Download } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ChartSpec, ResearchSource, TableSpec } from "../types/research";
import { chartColors, chartCsv, chartPng, chartRows, downloadBlob, serializeChartSvg } from "./reportVisualExports";

function citedSources(ids: string[], sources: ResearchSource[], onPreview: (source: ResearchSource) => void) {
  return [...new Set(ids)].map((id) => {
    const source = sources.find((item) => item.id === id);
    return source ? <button key={id} type="button" className="citation-chip" title={source.title} aria-label={`Preview reference ${sources.indexOf(source) + 1}: ${source.title}`} onClick={() => onPreview(source)}>[{sources.indexOf(source) + 1}]</button> : null;
  });
}

function ChartFigure({ chart, sources, onPreview }: { chart: ChartSpec; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  const plot = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDetailsElement>(null);
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const rows = chartRows(chart);
  const validSeries = chart.series.filter((series) => rows.some((row) => typeof row[series.key] === "number"));
  const referencesAvailable = chart.source_ids.length > 0 && chart.source_ids.every((id) => sources.some((source) => source.id === id));
  const canRender = referencesAvailable && validSeries.length > 0 && (chart.type !== "pie" || rows.some((row) => Number(row[chart.series[0]?.key]) > 0));
  const exportChart = async (format: "png" | "svg" | "csv") => {
    if (menu.current) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); }
    setExporting(true); setMessage(""); setFailed(false);
    try {
      const filename = chart.id.replace(/[^a-zA-Z0-9_-]/g, "-") || "research-chart";
      if (format === "csv") downloadBlob(`${filename}.csv`, new Blob([chartCsv(chart, rows)], { type: "text/csv;charset=utf-8" }));
      else {
        const surface = plot.current?.querySelector<SVGSVGElement>("svg.recharts-surface");
        if (!surface) throw new Error("The chart is not ready yet. Try again when it is visible.");
        const svg = serializeChartSvg(surface, chart, sources);
        downloadBlob(`${filename}.${format}`, format === "png" ? await chartPng(svg) : new Blob([svg.content], { type: "image/svg+xml;charset=utf-8" }));
      }
      setMessage(`${format.toUpperCase()} download started.`);
    } catch (error) { setFailed(true); setMessage(error instanceof Error ? error.message : "The chart could not be downloaded. Please try again."); }
    finally { setExporting(false); }
  };
  const chartProps = { data: rows, margin: { top: 12, right: 20, left: 16, bottom: 24 } };
  const xLabel = chart.x_key.replace(/_/g, " ");
  const yLabel = validSeries.map((series) => series.label).join(" / ");
  const axes = <><CartesianGrid stroke="#94a3b8" strokeDasharray="3 3" opacity={0.25} /><XAxis dataKey={chart.x_key} tick={{ fill: "#64748b", fontSize: 11 }} label={{ value: xLabel, position: "insideBottom", offset: -16, fill: "#64748b", fontSize: 11 }} /><YAxis tick={{ fill: "#64748b", fontSize: 11 }} label={{ value: yLabel, angle: -90, position: "insideLeft", offset: -6, fill: "#64748b", fontSize: 11 }} /><Tooltip /><Legend verticalAlign="top" wrapperStyle={{ paddingBottom: 16, fontSize: 12 }} /></>;
  const series = validSeries.map((item) => {
    const color = item.color || chartColors[chart.series.indexOf(item) % chartColors.length];
    if (chart.type === "bar") return <Bar key={item.key} dataKey={item.key} name={item.label} fill={color} isAnimationActive={false} />;
    if (chart.type === "area") return <Area key={item.key} dataKey={item.key} name={item.label} type="linear" stroke={color} fill={color} fillOpacity={0.12} connectNulls={false} isAnimationActive={false} />;
    return <Line key={item.key} dataKey={item.key} name={item.label} type="linear" stroke={color} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />;
  });
  const pieRows = rows.filter((row) => typeof row[chart.series[0]?.key] === "number");
  const rendered = chart.type === "pie"
    ? <PieChart><Tooltip /><Legend verticalAlign="top" wrapperStyle={{ fontSize: 12 }} /><Pie data={pieRows} dataKey={chart.series[0]?.key || "value"} nameKey={chart.x_key} outerRadius="70%" label isAnimationActive={false}>{pieRows.map((_, index) => <Cell key={index} fill={chartColors[index % chartColors.length]} />)}</Pie></PieChart>
    : chart.type === "bar" ? <BarChart {...chartProps}>{axes}{series}</BarChart>
      : chart.type === "area" ? <AreaChart {...chartProps}>{axes}{series}</AreaChart>
        : chart.type === "scatter" ? <ScatterChart margin={chartProps.margin}><CartesianGrid stroke="#94a3b8" strokeDasharray="3 3" opacity={0.25} /><XAxis dataKey={chart.x_key} type="number" name={xLabel} tick={{ fill: "#64748b", fontSize: 11 }} label={{ value: xLabel, position: "insideBottom", offset: -16, fill: "#64748b", fontSize: 11 }} /><YAxis dataKey="__value" type="number" name={yLabel} tick={{ fill: "#64748b", fontSize: 11 }} label={{ value: yLabel, angle: -90, position: "insideLeft", offset: -6, fill: "#64748b", fontSize: 11 }} /><Tooltip cursor={{ strokeDasharray: "3 3" }} /><Legend verticalAlign="top" wrapperStyle={{ paddingBottom: 16, fontSize: 12 }} />{validSeries.map((item) => <Scatter key={item.key} name={item.label} data={rows.filter((row) => typeof row[item.key] === "number").map((row) => ({ [chart.x_key]: row[chart.x_key], __value: row[item.key] }))} fill={item.color || chartColors[chart.series.indexOf(item) % chartColors.length]} isAnimationActive={false} />)}</ScatterChart>
          : <LineChart {...chartProps}>{axes}{series}</LineChart>;
  return <figure className="report-visual min-w-0" aria-label={chart.title}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <h3 className="m-0 text-base font-semibold">{chart.title}</h3>
      {canRender && <details ref={menu} className="chart-download no-print relative shrink-0" onKeyDown={(event) => { if (event.key === "Escape" && menu.current) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); } }}><summary aria-label={`Download ${chart.title}`} className="button-secondary flex cursor-pointer list-none items-center gap-1"><Download size={14} aria-hidden="true" /> {exporting ? "Preparing…" : "Download"}</summary><div className="absolute right-0 z-10 mt-1 grid min-w-28 gap-1 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">{(["png", "svg", "csv"] as const).map((format) => <button key={format} type="button" disabled={exporting} className="download-item" onClick={() => void exportChart(format)}>{format.toUpperCase()}</button>)}</div></details>}
    </div>
    {canRender ? <><div ref={plot} className="report-chart-plot mt-4 h-80 min-w-0 w-full" aria-label={`${chart.title}. ${chart.caption}`}><ResponsiveContainer width="100%" height="100%" minWidth={0}>{rendered}</ResponsiveContainer></div><details className="mt-2 text-xs"><summary className="cursor-pointer text-slate-500">View chart data</summary><div className="report-table-wrap" tabIndex={0} role="region" aria-label={`${chart.title} data`}><table><thead><tr><th scope="col">{xLabel}</th>{chart.series.map((item) => <th scope="col" key={item.key}>{item.label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}><th scope="row">{String(row[chart.x_key])}</th>{chart.series.map((item) => <td key={item.key}>{row[item.key] === null || row[item.key] === undefined ? "Not reported" : String(row[item.key])}</td>)}</tr>)}</tbody></table></div></details></> : <p className="my-5 text-sm text-slate-500">This chart is unavailable because its measurements or retrieved source references are missing. No values have been estimated.</p>}
    <figcaption className="mt-3 text-sm text-slate-500"><span>{chart.caption}</span><span className="mt-1 block">Sources: {citedSources(chart.source_ids, sources, onPreview)}</span></figcaption>
    {message && <p role={failed ? "alert" : "status"} className={`chart-download mt-2 text-xs ${failed ? "text-red-600" : "text-slate-500"}`}>{message}</p>}
  </figure>;
}

export function ReportVisuals({ charts, tables, sources, onPreview }: { charts: ChartSpec[]; tables: TableSpec[]; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  return <div className="min-w-0 space-y-8">{tables.map((table) => <figure key={table.id} className="report-table-figure min-w-0" aria-label={table.title}><h3 className="text-base font-semibold">{table.title}</h3><div className="report-table-wrap mt-4" tabIndex={0} role="region" aria-label={`${table.title} table`}><table><thead><tr>{table.columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead><tbody>{table.rows.map((row, index) => <tr key={index}>{table.columns.map((column) => <td key={column}>{String(row[column] ?? "Not reported")}</td>)}</tr>)}</tbody></table></div><figcaption className="mt-2 text-sm text-slate-500">{table.caption}<span className="mt-1 block">Sources: {citedSources(table.source_ids, sources, onPreview)}</span></figcaption></figure>)}{charts.map((chart) => <ChartFigure key={chart.id} chart={chart} sources={sources} onPreview={onPreview} />)}</div>;
}