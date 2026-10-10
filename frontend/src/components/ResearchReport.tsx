import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Root, Element, Text } from "hast";
import { Citation } from "./Citation";
import { ReportVisuals } from "./ReportVisuals";
import type { ReportSection, ResearchSource, StructuredReport } from "../types/research";

// Legacy Markdown remains readable; current reports use the backend's ordered sections.
export function splitReport(markdown: string): { title: string; sections: ReportSection[] } {
  const title = markdown.match(/^#\s+(.+)$/m)?.[1] || "Research report";
  const chunks = markdown.split(/^##\s+/m);
  const sections = chunks.slice(1).map((chunk, index) => {
    const lineBreak = chunk.indexOf("\n");
    return { id: `section-${index + 1}`, title: (lineBreak < 0 ? chunk : chunk.slice(0, lineBreak)).trim(), content: lineBreak < 0 ? "" : chunk.slice(lineBreak + 1).trim() };
  });
  if (!sections.length) sections.push({ id: "body", title: "Research report", content: markdown.replace(/^#\s+.+\n?/, "").trim() });
  return { title, sections };
}

export function ResearchReport({ markdown, sources, onPreview, structured }: { markdown: string; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void; structured?: StructuredReport }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [count, setCount] = useState(0);
  const article = useRef<HTMLElement>(null);
  useEffect(() => {
    let folded: HTMLDetailsElement[] = [];
    const expand = () => { folded = Array.from(article.current?.querySelectorAll<HTMLDetailsElement>('.report-reading-notes:not([open])') || []); folded.forEach(item => { item.open = true; }); };
    const restore = () => { folded.forEach(item => { item.open = false; }); folded = []; };
    window.addEventListener('beforeprint', expand); window.addEventListener('afterprint', restore);
    return () => { window.removeEventListener('beforeprint', expand); window.removeEventListener('afterprint', restore); };
  }, []);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  const report = useMemo(() => structured?.sections.length ? structured : splitReport(markdown), [structured, markdown]);
  const sectionIds = new Set(report.sections.map((section) => section.id));
  const visualSection = (item: { section_id?: string; origin?: string }) => {
    if (item.section_id && sectionIds.has(item.section_id)) return item.section_id;
    const preferred = item.origin === "session" ? "methodology" : "comparison";
    return sectionIds.has(preferred) ? preferred : report.sections[report.sections.length - 1]?.id;
  };
  const readingContent = (content: string) => {
    const notes: string[] = [];
    const text = content.split(/\n\s*\n/).filter(paragraph => {
      if (/^(Interpretive boundary:|The evidence trail for this assessment is reproduced below\.)/.test(paragraph)) { notes.push(paragraph); return false; }
      return true;
    }).join('\n\n');
    return { text, notes: [...new Set(notes)] };
  };
  const linkedText = (text: string) => text.replace(/\[((?:S\d+|\d+)(?:\s*[,;]\s*(?:S\d+|\d+))*)\](?!\()/g, (_original, group: string) => group.split(/[,;]/).map((token) => {
    const id = token.trim();
    const source = id.startsWith("S") ? sources.find((item) => item.id === id) : sources[Number(id) - 1];
    return source ? `[${sources.indexOf(source) + 1}](#source-${source.id})` : "[citation unavailable]";
  }).join(" "));
  const highlight = useMemo(() => () => (tree: Root) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return;
    const visit = (node: Root | Element) => {
      for (let childIndex = node.children.length - 1; childIndex >= 0; childIndex--) {
        const child = node.children[childIndex];
        if (child.type === "element") { visit(child); continue; }
        if (child.type !== "text") continue;
        const text = child.value;
        const parts: (Text | Element)[] = [];
        let start = 0, index = text.toLowerCase().indexOf(needle);
        while (index >= 0) {
          if (index > start) parts.push({ type: "text", value: text.slice(start, index) });
          parts.push({ type: "element", tagName: "mark", properties: {}, children: [{ type: "text", value: text.slice(index, index + needle.length) }] });
          start = index + needle.length; index = text.toLowerCase().indexOf(needle, start);
        }
        if (start < text.length) parts.push({ type: "text", value: text.slice(start) });
        node.children.splice(childIndex, 1, ...parts);
      }
    };
    visit(tree);
  }, [query]);
  useEffect(() => { setCount(article.current?.querySelectorAll("mark").length || 0); setActive(0); }, [query, report]);
  useEffect(() => {
    const matches = article.current?.querySelectorAll("mark");
    matches?.forEach((mark, index) => mark.classList.toggle("report-match-current", index === active));
    if (query.trim()) {
      const match = matches?.[active];
      const details = match?.closest('details');
      if (details) details.open = true;
      match?.scrollIntoView({ block: 'center' });
    }
  }, [active, count, query]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "research-report.md"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown); setCopied(true); setCopyError("");
      clearTimeout(copyTimer.current); copyTimer.current = setTimeout(() => setCopied(false), 1800);
    } catch { setCopyError("Clipboard access failed. Download the Markdown report instead."); }
  };
  return <section id="final-report" tabIndex={-1} className="report-wrapper print-report scroll-mt-24" aria-label="Final research report">
    <header className="report-toolbar no-print border-b border-border px-5 py-5 dark:border-border">
      <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 className="text-lg font-medium">Research report</h2><p className="text-xs text-muted-foreground">{report.sections.length} sections · {sources.length} retrieved sources</p></div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="button-secondary" title="Copy the complete report" onClick={copy}>{copied ? "Copied" : "Copy report"}</button>
        <button className="button-secondary" title="Download the report as Markdown" onClick={download}>Export Markdown</button>
        <button className="button-secondary" title="Open the browser print dialog" onClick={() => window.print()}>Print</button>
        <button className="button-secondary" onClick={() => window.print()} title="Choose Save as PDF in your browser print dialog">Export PDF</button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">PDF export uses your browser’s “Save as PDF” destination.</p>
      {copyError && <p role="alert" className="mt-2 text-sm text-destructive">{copyError}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2"><label htmlFor="report-search" className="sr-only">Search within report</label><input id="report-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search within report" className="select min-h-10 min-w-0 flex-1" /><span aria-live="polite" className="text-xs">{count ? active + 1 : 0} / {count}</span><button aria-label="Previous match" disabled={!count} className="button-secondary" onClick={() => setActive((active + count - 1) % count)}>Previous</button><button aria-label="Next match" disabled={!count} className="button-secondary" onClick={() => setActive((active + 1) % count)}>Next</button></div>
    </header>
    <div className="report-layout">
      <article ref={article} className="report-content report-document">
        <p className="report-kicker">Evidence-led research / Final document</p>
        <h1 className="report-document-title">{report.title}</h1>
        {report.sections.map((section, index) => <section key={section.id} id={`report-${section.id}`} className="report-document-section" aria-labelledby={`report-heading-${section.id}`}>
          <h2 id={`report-heading-${section.id}`}><span className="report-section-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>{section.title}</h2>
          <ReactMarkdown disallowedElements={['img']} remarkPlugins={[remarkGfm]} rehypePlugins={[highlight]} components={{
            table: ({ children }) => <div className="report-table-wrap" tabIndex={0} role="region" aria-label={`${section.title} table`}><table>{children}</table></div>,
            a: ({ href, children }) => {
              const source = sources.find((item) => href === "#source-" + item.id);
              return source ? <Citation n={sources.indexOf(source) + 1} onClick={() => onPreview(source)} /> : <a href={href} target={href?.startsWith("#") ? undefined : "_blank"} rel="noreferrer">{children}</a>;
            },
          }}>{linkedText(readingContent(section.content).text)}</ReactMarkdown>
          {readingContent(section.content).notes.length > 0 && <details className="report-reading-notes"><summary className="cursor-pointer text-sm text-muted-foreground">Evidence and interpretation notes</summary><ReactMarkdown disallowedElements={['img']} remarkPlugins={[remarkGfm]} rehypePlugins={[highlight]}>{readingContent(section.content).notes.join('\n\n')}</ReactMarkdown></details>}
          {structured && <ReportVisuals charts={structured.charts.filter((item) => visualSection(item) === section.id)} tables={structured.tables.filter((item) => visualSection(item) === section.id)} sources={sources} onPreview={onPreview} />}
        </section>)}
        {structured && !structured.charts.length && !structured.tables.length && <p className="report-visual-status">No validated chart or table data was available for this research session. Visuals are shown only when the retrieved evidence contains traceable measurements or the research state contains quality/status data.</p>}
      </article>
      <nav className="report-toc" aria-label="Report sections"><div className="report-toc-inner"><p className="eyebrow">In this report</p><ol>{report.sections.map((section, index) => <li key={section.id}><a href={`#report-${section.id}`}><span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>{section.title}</a></li>)}</ol></div></nav>
    </div>
  </section>;
}
