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
    {open && <div role="dialog" aria-label="About Research Agent" className="absolute right-0 top-12 z-40 w-72 rounded-xl border border-border bg-surface p-4 text-sm shadow-soft dark:border-border dark:bg-surface">
      <div className="flex items-start justify-between gap-3"><div><p className="font-medium"> Aman Poddar</p><p className="text-xs text-muted-foreground">Software Engineer</p></div><button className="icon-button p-1" aria-label="Close about dialog" onClick={() => setOpen(false)}><X size={15} /></button></div>
      <a className="mt-3 inline-block text-xs text-link underline dark:text-link" href="https://www.linkedin.com/in/aman-poddar12/" target="_blank" rel="noopener noreferrer">LinkedIn</a>
      <div className="mt-4 border-t border-border pt-3 dark:border-border"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">About this product</p><p className="mt-2 text-xs leading-5 text-muted-foreground dark:text-muted-foreground">Research is slow and scattered, and sources are hard to verify. Research Agent helps students, researchers, and professionals get cited research quickly through multi-mode research, source-quality scoring, citation validation, structured long-form reports with charts and tables, and PDF or Markdown export. Completed work can be saved locally in this browser.</p></div>
    </div>}
  </div>;
}
