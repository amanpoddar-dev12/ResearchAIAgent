import { BrainCircuit, Moon, Sun, Plus } from "lucide-react";

export function Header({ dark, onTheme, onNew }: { dark: boolean; onTheme: () => void; onNew: () => void }) {
  return <header className="border-b border-slate-200/80 bg-white/80 dark:border-slate-800 dark:bg-slate-950/80">
    <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4 lg:px-8">
      <div className="flex min-w-0 items-center gap-2 font-semibold"><span className="shrink-0 rounded-lg bg-indigo-600 p-2 text-white"><BrainCircuit aria-hidden="true" size={18} /></span><span className="truncate">Research Agent</span></div>
      <div className="flex shrink-0 items-center gap-1 sm:gap-2"><button onClick={onNew} className="button-secondary min-h-10 px-2 sm:px-3" aria-label="Start new research"><Plus aria-hidden="true" size={16} /><span className="hidden sm:inline">New Research</span></button><button aria-label="Toggle theme" onClick={onTheme} className="icon-button min-h-10 min-w-10">{dark ? <Sun aria-hidden="true" size={18} /> : <Moon aria-hidden="true" size={18} />}</button></div>
    </div>
  </header>;
}
