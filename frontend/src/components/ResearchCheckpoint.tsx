import { useState } from 'react';
import { libraryRequest } from '../services/api';
import type { ResearchEvent, ResearchGap, ResearchSource } from '../types/research';
interface Review { token: string; sources: ResearchSource[]; gaps: ResearchGap[]; canInvestigate: boolean; expiresInSeconds: number }
export function ResearchCheckpoint({ events, onPreview }: { events: ResearchEvent[]; onPreview: (source: ResearchSource) => void }) {
  const latest = [...events].reverse().find(event => ['research_checkpoint', 'checkpoint_resumed', 'synthesis_started', 'research_failed', 'complete'].includes(event.type));
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (latest?.type !== 'research_checkpoint' || !latest.research_id) return null;
  const review = latest.data as Review;
  const resume = async () => { setBusy(true); setError(''); try { await libraryRequest(`research/${latest.research_id}/checkpoint`, { method: 'POST', body: JSON.stringify({ token: review.token, gap_ids: review.canInvestigate ? selected : [] }) }); } catch (error) { setError(error instanceof Error ? error.message : 'Review could not be submitted.'); setBusy(false); } };
  return <section className="card report-full-width no-print" aria-label="Research checkpoint"><h2 className="section-title">Review before the report</h2><p className="mt-2 text-sm text-muted-foreground">Inspect the sources and select up to three gaps for the remaining research budget. After 15 minutes, research continues automatically.</p><div className="mt-3 flex flex-wrap gap-2">{review.sources.map(source => <button key={source.id} className="chip" onClick={() => onPreview(source)}>{source.id}: {source.title}</button>)}</div>{!review.canInvestigate && <p className="mt-3 text-sm">No follow-up budget remains; you can review sources and continue to the report.</p>}<div className="mt-4 space-y-3">{review.gaps.map(gap => <label key={gap.gap_id} className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={!review.canInvestigate || busy || selected.length >= 3 && !selected.includes(gap.gap_id)} checked={selected.includes(gap.gap_id)} onChange={event => setSelected(items => event.target.checked ? [...items, gap.gap_id] : items.filter(id => id !== gap.gap_id))} />{gap.description}</label>)}</div><button className="button-primary mt-4" disabled={busy} onClick={() => void resume()}>{busy ? 'Continuing…' : selected.length ? 'Investigate selected gaps' : 'Continue to report'}</button>{error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}</section>;
}
