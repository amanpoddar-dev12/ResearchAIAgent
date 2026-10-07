import { useEffect, useState } from "react";
import type { Theme } from "../theme";
import { BookOpen, FileCheck2, FileText, Gauge, ListChecks, MessageCircle, Plus, Settings2, ShieldAlert, BrainCircuit, UserRound, X } from "lucide-react";
import type { SavedResearch } from "../storage/researchStorage";

const groups = [
  { title: "Research", items: [["Current Research", Gauge, "#main-content"], ["Research Settings", Settings2, "#research-settings"]] },
  { title: "Evidence", items: [["Sources", BookOpen, "#sources"], ["Findings", ListChecks, "#findings"], ["Evidence", FileCheck2, "#evidence"], ["Conflicts", ShieldAlert, "#conflicts"]] },
  { title: "Report", items: [["Final Report", FileText, "#final-report"]] },
] as const;

export function Sidebar({ open, onClose, onNew, saved, onOpenSaved, onRenameSaved, onDeleteSaved, onClearSaved, activeView, onViewChange, theme, onTheme }: { open: boolean; onClose: () => void; onNew: () => void; saved: SavedResearch[]; onOpenSaved: (item: SavedResearch) => void; onRenameSaved: (item: SavedResearch) => void; onDeleteSaved: (id: string) => void; onClearSaved: () => void; activeView: "research" | "assistant"; onViewChange: (view: "research" | "assistant") => void; theme: Theme; onTheme: (theme: Theme) => void }) {
  const [section, setSection] = useState(() => window.location.hash || "#main-content");
  useEffect(() => { const update = () => setSection(window.location.hash || "#main-content"); window.addEventListener("hashchange", update); return () => window.removeEventListener("hashchange", update); }, []);
  return <><button aria-label="Close navigation" className={`drawer-backdrop ${open ? "block" : "hidden"}`} onClick={onClose} />
    <aside className={`sidebar no-print ${open ? "translate-x-0" : "-translate-x-full"}`} aria-label="Research navigation">
      <div className="flex items-center justify-between"><div className="flex items-center gap-2"><span className="app-mark"><BrainCircuit size={24} /></span><span className="font-medium">Research Agent</span></div><button className="icon-button md:hidden" onClick={onClose} aria-label="Close navigation"><X size={18} /></button></div>
      <button className="button-primary mt-7 w-full justify-center" onClick={() => { onNew(); onClose(); }}><Plus size={16} /> New Research</button>
      <div className="sidebar-content min-h-0 flex-1 overflow-y-auto">
      <nav className="mt-5 space-y-4" aria-label="Research sections">{groups.map((group) => <section key={group.title}><p className="eyebrow mb-2 px-3">{group.title}</p><div className="space-y-1">{group.items.map(([label, Icon, href]) => <a key={label} href={href} className="sidebar-link" onClick={() => { onViewChange("research"); onClose(); }} aria-current={activeView === "research" && section === href ? "location" : undefined}><Icon size={18} />{label}</a>)}{group.title === "Research" && <button type="button" className="sidebar-link w-full" aria-current={activeView === "assistant" ? "page" : undefined} onClick={() => { onViewChange("assistant"); onClose(); }}><MessageCircle size={18} />Research Assistant</button>}</div></section>)}</nav>
      <div className="mt-8">
        <div className="flex items-center justify-between"><p className="eyebrow">Saved research</p>{saved.length > 0 && <button className="text-[11px] text-muted-foreground hover:text-destructive" onClick={onClearSaved}>Clear all</button>}</div>
        {saved.length === 0 ? <p className="mt-3 text-xs leading-5 text-muted-foreground">Completed reports saved in this browser appear here.</p> :
          <div className="mt-2 space-y-1">{saved.slice(0, 8).map((item) => <div key={item.id} className="group flex items-center gap-1"><button className="min-w-0 flex-1 truncate rounded-lg px-2 py-2 text-left text-xs text-muted-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-surface" onClick={() => { onOpenSaved(item); onClose(); }} title={item.name || item.question}>{item.name || item.question}</button><button className="text-[10px] text-muted-foreground hover:text-link " onClick={() => onRenameSaved(item)} aria-label={`Rename ${item.name || item.question}`}>Rename</button><button className="text-[10px] text-muted-foreground hover:text-destructive " onClick={() => onDeleteSaved(item.id)} aria-label={`Delete ${item.name || item.question}`}>×</button></div>)}</div>}
      </div>
      <p className="eyebrow mt-8">Research modes</p><div className="mt-3 flex flex-wrap gap-2"><span className="badge badge-indigo">Quick</span><span className="badge">Deep</span><span className="badge">Academic</span></div>
      </div>
      <div className="sidebar-footer shrink-0"><div className="border-t border-border pt-4"><label className="mb-2 block text-xs text-muted-foreground" htmlFor="workspace-theme">Appearance</label><select id="workspace-theme" className="select w-full" value={theme} onChange={(event) => onTheme(event.target.value as Theme)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select><div className="mt-4 flex items-center gap-3"><UserRound /><div><p className="text-sm font-medium">Local workspace</p><p className="text-xs text-muted-foreground">Saved in this browser</p></div></div></div></div>
    </aside>
  </>;
}
