import { Check, Clipboard, Download, FileText, Printer } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ResearchReport({ markdown }: { markdown: string }) {
  const [copied, setCopied] = useState(false);
  const title = markdown.match(/^#\s+(.+)$/m)?.[1] || "Research Report";
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "research-report.md";
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const downloadPdf = () => window.print();
  const copy = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };
  return <section className="report-wrapper min-w-0 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
    <header className="border-b border-slate-100 bg-gradient-to-br from-indigo-50 via-white to-white px-6 py-6 dark:border-slate-800 dark:from-indigo-950/40 dark:via-slate-900 dark:to-slate-900 sm:px-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="rounded-2xl bg-indigo-600 p-2.5 text-white"><FileText aria-hidden="true" size={20} /></span>
          <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">Evidence brief</p><h2 className="mt-1 break-words text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">{title}</h2><p className="mt-2 text-sm text-slate-500">Sourced analysis generated from the collected evidence.</p></div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button className="icon-button focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" aria-label={copied ? "Report copied" : "Copy report"} title={copied ? "Report copied" : "Copy report"} onClick={copy}>{copied ? <Check aria-hidden="true" size={16} /> : <Clipboard aria-hidden="true" size={16} />}</button>
          <button className="icon-button focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" aria-label="Download Markdown report" title="Download Markdown" onClick={download}><Download aria-hidden="true" size={16} /></button>
          <button className="icon-button focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" aria-label="Download PDF report" title="Download PDF" onClick={downloadPdf}><Printer aria-hidden="true" size={16} /></button>
        </div>
      </div>
    </header>
    <article className="report-content px-4 py-6 sm:px-8 sm:py-9"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className="report-table-wrap"><table>{children}</table></div> }}>{markdown}</ReactMarkdown></article>
  </section>;
}
