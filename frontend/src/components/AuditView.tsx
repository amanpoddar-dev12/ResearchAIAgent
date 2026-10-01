import { useState } from "react";
import type { AuditEntry } from "../types/research";

export function AuditView({ entries }: { entries: AuditEntry[] }) {
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("");
  const shown = entries.filter((entry) => (!action || entry.action === action) && `${entry.message} ${JSON.stringify(entry.details)}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="card" aria-label="Session audit trail">
    <h2 className="text-lg font-semibold">Research audit</h2>
    <div className="mt-3 flex flex-wrap gap-2"><input aria-label="Search audit" placeholder="Search decisions…" value={query} onChange={(event) => setQuery(event.target.value)} className="select min-w-0 flex-1" /><select aria-label="Audit action" value={action} onChange={(event) => setAction(event.target.value)} className="select"><option value="">All actions</option>{[...new Set(entries.map((entry) => entry.action))].map((item) => <option key={item} value={item}>{item.replace(/_/g, " ")}</option>)}</select></div>
    <p className="mt-2 text-xs text-slate-500">{shown.length} of {entries.length} session decisions</p>
    <ol className="mt-3 max-h-96 space-y-3 overflow-auto">{shown.map((entry) => <li key={entry.id} className="border-l-2 border-indigo-200 pl-3 text-xs"><div className="text-slate-500"><time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString()}</time> · {entry.action.replace(/_/g, " ")}</div><p className="mt-1 break-words">{entry.message}</p>{Object.keys(entry.details).length > 0 && <details className="mt-1"><summary className="cursor-pointer">Details</summary><pre className="mt-1 whitespace-pre-wrap break-words font-sans">{JSON.stringify(entry.details, null, 2)}</pre></details>}</li>)}</ol>
    {!shown.length && <p className="mt-3 text-sm text-slate-500">No matching decisions yet.</p>}
  </section>;
}