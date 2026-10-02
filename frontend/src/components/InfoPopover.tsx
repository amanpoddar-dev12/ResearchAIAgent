import { Info, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function InfoPopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="relative no-print" ref={ref}>
    <button type="button" className="icon-button min-h-10 min-w-10" aria-label="About Research Agent" aria-expanded={open} onClick={() => setOpen((value) => !value)}><Info size={18} /></button>
    {open && <div role="dialog" aria-label="About Research Agent" className="absolute right-0 top-12 z-40 w-72 rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-xl dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3"><div><p className="font-semibold"> Aman Poddar</p><p className="text-xs text-slate-500">Software Engineer</p></div><button className="icon-button p-1" aria-label="Close about dialog" onClick={() => setOpen(false)}><X size={15} /></button></div>
      <a className="mt-3 inline-block text-xs text-indigo-600 underline dark:text-indigo-300" href="https://www.linkedin.com/in/aman-poddar12/" target="_blank" rel="noopener noreferrer">LinkedIn</a>
      <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">About this product</p><p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">Research is slow and scattered, and sources are hard to verify. Research Agent helps students, researchers, and professionals get cited research quickly through multi-mode research, source-quality scoring, citation validation, structured long-form reports with charts and tables, and PDF or Markdown export. Completed work can be saved locally in this browser.</p></div>
    </div>}
  </div>;
}
