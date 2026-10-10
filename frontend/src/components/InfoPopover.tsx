import { CircleHelp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function InfoPopover({ sidebar = false }: { sidebar?: boolean }) {
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
    <button type="button" className={sidebar ? "sidebar-link min-h-11 w-full" : "icon-button min-h-10 min-w-10"} aria-label="About FindingsAI" aria-expanded={open} onClick={() => setOpen((value) => !value)}><CircleHelp size={18} />{sidebar && <span>About FindingsAI</span>}</button>
    {open && <div role="dialog" aria-label="About FindingsAI" className={`${sidebar ? 'bottom-full left-0 mb-2 w-full' : 'right-0 top-12 w-72'} absolute z-40 rounded-xl border border-border bg-surface p-4 text-sm shadow-soft dark:border-border dark:bg-surface`}>
      <div className="flex items-start justify-between gap-3"><div><p className="font-medium">Founded By Aman Poddar</p><p className="text-xs text-muted-foreground">Software Engineer</p></div><button className="icon-button p-1" aria-label="Close about dialog" onClick={() => setOpen(false)}><X size={15} /></button></div>
      <a className="mt-3 inline-block text-xs text-link underline dark:text-link" href="https://www.linkedin.com/in/aman-poddar12/" target="_blank" rel="noopener noreferrer">LinkedIn</a>
      <p className="mt-3 text-xs text-muted-foreground">Share feedback: <a className="break-all text-link underline" href="mailto:amanpoddar775@gmail.com">amanpoddar775@gmail.com</a></p>
      <div className="mt-4 border-t border-border pt-3 dark:border-border"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">About this product</p><p className="mt-2 text-xs leading-5 text-muted-foreground dark:text-muted-foreground">FindingsAI turns research questions into structured reports with source-backed findings, inline citations, and evidence you can inspect. Explore sources, ask follow-up questions, and export your report.</p></div>
    </div>}
  </div>;
}
