import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Root, Element, Text } from "hast";
import { Citation } from "./Citation";
import type { ResearchSource } from "../types/research";

export function ResearchReport({ markdown, sources, onPreview }: { markdown: string; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [count, setCount] = useState(0);
  const article = useRef<HTMLElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  const linkedMarkdown = useMemo(() => markdown.replace(/\[(\d+)\](?!\()/g, (original, number: string) => {
    const source = sources[Number(number) - 1];
    return source ? "[" + number + "](#source-" + source.id + ")" : original;
  }), [markdown, sources]);
  const headings = useMemo(() => [...markdown.matchAll(/^#{2,3}\s+(.+)$/gm)].map((match) => ({ label: match[1].replace(/[*_`]/g, ""), id: match[1].toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") })), [markdown]);
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
  useEffect(() => { setCount(article.current?.querySelectorAll("mark").length || 0); setActive(0); }, [query, markdown]);
  useEffect(() => {
    const matches = article.current?.querySelectorAll("mark");
    matches?.forEach((mark, index) => mark.classList.toggle("report-match-current", index === active));
    if (query.trim()) matches?.[active]?.scrollIntoView({ block: "center" });
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
  return <section id="final-report" className="report-wrapper min-w-0 overflow-hidden rounded-3xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
    <header className="report-toolbar border-b border-slate-100 p-5 dark:border-slate-800">
      <h2 className="text-lg font-semibold">Research report</h2>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="button-secondary" onClick={copy}>{copied ? "Copied" : "Copy report"}</button>
        <button className="button-secondary" onClick={download}>Export Markdown</button>
        <button className="button-secondary" onClick={() => window.print()}>Print</button>
        <button className="button-secondary" onClick={() => window.print()} title="Choose Save as PDF in your browser print dialog">Export PDF</button>
      </div>
      <p className="mt-2 text-xs text-slate-500">PDF export uses your browser’s “Save as PDF” destination.</p>
      {copyError && <p role="alert" className="mt-2 text-sm text-red-600">{copyError}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2"><label htmlFor="report-search" className="sr-only">Search within report</label><input id="report-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search within report" className="select min-h-10 flex-1" /><span aria-live="polite" className="text-xs">{count ? active + 1 : 0} / {count}</span><button aria-label="Previous match" disabled={!count} className="button-secondary" onClick={() => setActive((active + count - 1) % count)}>Previous</button><button aria-label="Next match" disabled={!count} className="button-secondary" onClick={() => setActive((active + 1) % count)}>Next</button></div>
    </header>
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_180px]">
    <article ref={article} className="report-content px-4 py-6 sm:px-8">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[highlight]} components={{
        table: ({ children }) => <div className="report-table-wrap"><table>{children}</table></div>,
        h2: ({ children }) => { const label = String(children); const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); return <h2 id={id}>{children}</h2>; },
        a: ({ href, children }) => {
          const source = sources.find((source) => href === "#source-" + source.id);
          return source ? <Citation n={sources.indexOf(source) + 1} onClick={() => onPreview(source)} /> : <a href={href} target="_blank" rel="noreferrer">{children}</a>;
        },
      }}>{linkedMarkdown}</ReactMarkdown>
    </article>
    {headings.length > 0 && <nav className="order-first hidden border-l border-slate-100 p-4 lg:order-last lg:block dark:border-slate-800" aria-label="Report sections"><p className="eyebrow">On this page</p><div className="mt-3 space-y-2">{headings.map((heading) => <a key={heading.id} href={`#${heading.id}`} className="block text-xs text-slate-500 hover:text-indigo-600">{heading.label}</a>)}</div></nav>}
    </div>
  </section>;
}
