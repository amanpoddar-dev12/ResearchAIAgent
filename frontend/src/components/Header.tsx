import { BrainCircuit, Menu, Moon, Sun, Plus } from "lucide-react";

export function Header({ dark, onTheme, onNew, onMenu, status, mode }: { dark: boolean; onTheme: () => void; onNew: () => void; onMenu: () => void; status: string; mode: string }) {
  return <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-[#f7f8fc]/90 backdrop-blur dark:border-slate-800 dark:bg-[#0b1020]/90">
    <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4 lg:px-8">
      <div className="flex min-w-0 items-center gap-3"><button className="icon-button lg:hidden" onClick={onMenu} aria-label="Open navigation"><Menu size={19} /></button><span className="shrink-0 rounded-xl bg-indigo-600 p-2.5 text-white shadow-sm"><BrainCircuit aria-hidden="true" size={18} /></span><div className="min-w-0"><div className="truncate text-sm font-semibold tracking-tight">Research Agent</div><div className="hidden text-xs text-slate-500 sm:block">Evidence, organized</div></div></div>
      <div className="flex shrink-0 items-center gap-1 sm:gap-2"><span className="badge hidden sm:inline-flex">{mode.replace("_", " ")} · {status}</span><button onClick={onNew} className="button-secondary min-h-10 px-2 sm:px-3" aria-label="Start new research"><Plus aria-hidden="true" size={16} /><span className="hidden sm:inline">New Research</span></button><button aria-label="Toggle theme" onClick={onTheme} className="icon-button min-h-10 min-w-10">{dark ? <Sun aria-hidden="true" size={18} /> : <Moon aria-hidden="true" size={18} />}</button></div>
    </div>
  </header>;
}
