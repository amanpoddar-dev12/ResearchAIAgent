import { BookOpen, FileCheck2, FileText, Gauge, ListChecks, Plus, Settings2, ShieldAlert, Sparkles, X } from "lucide-react";

const items = [
  ["Current Research", Gauge], ["Sources", BookOpen], ["Findings", ListChecks],
  ["Evidence", FileCheck2], ["Conflicts", ShieldAlert], ["Final Report", FileText], ["Research Settings", Settings2],
] as const;

export function Sidebar({ open, onClose, onNew }: { open: boolean; onClose: () => void; onNew: () => void }) {
  return <><button aria-label="Close navigation" className={`drawer-backdrop ${open ? "block" : "hidden"}`} onClick={onClose} />
    <aside className={`sidebar ${open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
      <div className="flex items-center justify-between"><div className="flex items-center gap-2"><Sparkles className="text-indigo-500" size={18} /><span className="font-semibold">Research workspace</span></div><button className="icon-button lg:hidden" onClick={onClose} aria-label="Close navigation"><X size={18} /></button></div>
      <button className="button-primary mt-7 w-full justify-center" onClick={() => { onNew(); onClose(); }}><Plus size={16} /> New Research</button>
      <p className="eyebrow mt-8">Workspace</p>
      <nav className="mt-2 space-y-1" aria-label="Research sections">{items.map(([label, Icon], index) => <a key={label} href={index === 0 ? "#main-content" : `#${label.toLowerCase().replace(/ /g, "-")}`} className="sidebar-link"><Icon size={16} />{label}</a>)}</nav>
      <p className="eyebrow mt-8">Research modes</p><div className="mt-3 flex flex-wrap gap-2"><span className="badge badge-indigo">Quick</span><span className="badge">Deep</span><span className="badge">Academic</span></div>
    </aside>
  </>;
}
