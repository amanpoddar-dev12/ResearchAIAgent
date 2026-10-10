import { useState } from 'react';
import type { SavedResearch } from '../storage/researchStorage';
export function VersionComparison({ current, saved }: { current: SavedResearch; saved: SavedResearch[] }) {
  const choices = saved.filter(item => item.id !== current.id);
  const [selected, setSelected] = useState(current.state.parent_research_id || '');
  const previous = choices.find(item => item.id === selected);
  const normalized = (claim: string) => claim.toLowerCase().replace(/\s+/g, ' ').trim();
  const oldClaims = new Map(previous?.state.findings.map(item => [normalized(item.claim), item]) || []);
  const newClaims = new Map(current.state.findings.map(item => [normalized(item.claim), item]));
  const added = current.state.findings.filter(item => !oldClaims.has(normalized(item.claim)));
  const changed = current.state.findings.filter(item => { const old = oldClaims.get(normalized(item.claim)); return old && old.evidence_status !== item.evidence_status; });
  const omitted = previous?.state.findings.filter(item => !newClaims.has(normalized(item.claim))) || [];
  return <details className="card no-print"><summary className="cursor-pointer text-sm font-medium">Compare research versions</summary><label className="mt-3 block text-xs">Previous report<select className="select mt-1 w-full" value={selected} onChange={event => setSelected(event.target.value)}><option value="">Choose a saved report</option>{choices.map(item => <option key={item.id} value={item.id}>{item.name || item.question} · {new Date(item.savedAt).toLocaleDateString()}</option>)}</select></label>{previous && <div className="mt-4 space-y-4 text-sm"><p className="text-xs text-muted-foreground">Exact claim text matches only. Added or omitted records do not prove a change in the world; paraphrases may appear as different claims.</p>{[['Added claim records', added], ['Revised evidence status', changed], ['Not investigated in this version', omitted]].map(([title, items]) => <section key={String(title)}><h3 className="text-sm font-medium">{String(title)} ({(items as typeof added).length})</h3><ul className="mt-2 space-y-2">{(items as typeof added).map(item => <li key={item.id || item.claim}>{item.claim} <span className="text-muted-foreground">— {title === 'Revised evidence status' ? `${oldClaims.get(normalized(item.claim))?.evidence_status} → ` : ''}{item.evidence_status}</span></li>)}</ul></section>)}<h3 className="text-sm font-medium">Remaining gaps</h3><ul>{current.state.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></div>}</details>;
}
