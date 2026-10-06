import { BookOpen, FileCheck2, FileText, Gauge, ListChecks, MessageCircle, Plus, Settings2, ShieldAlert, Sparkles, X } from "lucide-react";
import type { SavedResearch } from "../storage/researchStorage";

const items = [
  ["Current Research", Gauge], ["Sources", BookOpen], ["Findings", ListChecks],
  ["Evidence", FileCheck2], ["Conflicts", ShieldAlert], ["Final Report", FileText], ["Research Settings", Settings2],
] as const;

export function Sidebar({ open, onClose, onNew, saved, onOpenSaved, onRenameSaved, onDeleteSaved, onClearSaved, activeView, onViewChange }: { open: boolean; onClose: () => void; onNew: () => void; saved: SavedResearch[]; onOpenSaved: (item: SavedResearch) => void; onRenameSaved: (item: SavedResearch) => void; onDeleteSaved: (id: string) => void; onClearSaved: () => void; activeView: "research" | "assistant"; onViewChange: (view: "research" | "assistant") => void }) {
  return <><button aria-label="Close navigation" className={`drawer-backdrop ${open ? "block" : "hidden"}`} onClick={onClose} />
    <aside className={`sidebar no-print ${open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`} aria-label="Research navigation">
      <div className="flex items-center justify-between"><div className="flex items-center gap-2"><Sparkles className="text-indigo-500" size={18} /><span className="font-semibold">Research workspace</span></div><button className="icon-button lg:hidden" onClick={onClose} aria-label="Close navigation"><X size={18} /></button></div>
      <button className="button-primary mt-7 w-full justify-center" onClick={() => { onNew(); onClose(); }}><Plus size={16} /> New Research</button>
      <p className="eyebrow mt-8">Workspace</p>
      <nav className="mt-2 space-y-1" aria-label="Research sections">{items.map(([label, Icon], index) => <a key={label} href={index === 0 ? "#main-content" : `#${label.toLowerCase().replace(/ /g, "-")}`} className="sidebar-link" onClick={() => { onViewChange("research"); onClose(); }} aria-current={index === 0 && activeView === "research" ? "page" : undefined}><Icon size={16} />{label}</a>)}<button type="button" className={`sidebar-link w-full ${activeView === "assistant" ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" : ""}`} aria-current={activeView === "assistant" ? "page" : undefined} onClick={() => { onViewChange("assistant"); onClose(); }}><MessageCircle size={16} />Research Assistant</button></nav>
      <div className="mt-8">
        <div className="flex items-center justify-between"><p className="eyebrow">Saved research</p>{saved.length > 0 && <button className="text-[11px] text-slate-500 hover:text-red-600" onClick={onClearSaved}>Clear all</button>}</div>
        {saved.length === 0 ? <p className="mt-3 text-xs leading-5 text-slate-500">Completed reports saved in this browser appear here.</p> :
          <div className="mt-2 space-y-1">{saved.slice(0, 8).map((item) => <div key={item.id} className="group flex items-center gap-1"><button className="min-w-0 flex-1 truncate rounded-lg px-2 py-2 text-left text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900" onClick={() => { onOpenSaved(item); onClose(); }} title={item.name || item.question}>{item.name || item.question}</button><button className="hidden text-[10px] text-slate-400 hover:text-indigo-600 group-hover:inline" onClick={() => onRenameSaved(item)} aria-label={`Rename ${item.name || item.question}`}>Rename</button><button className="hidden text-[10px] text-slate-400 hover:text-red-600 group-hover:inline" onClick={() => onDeleteSaved(item.id)} aria-label={`Delete ${item.name || item.question}`}>×</button></div>)}</div>}
      </div>
      <p className="eyebrow mt-8">Research modes</p><div className="mt-3 flex flex-wrap gap-2"><span className="badge badge-indigo">Quick</span><span className="badge">Deep</span><span className="badge">Academic</span></div>
    </aside>
  </>;
}
