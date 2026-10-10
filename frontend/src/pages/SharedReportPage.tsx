import { useEffect, useState } from 'react';
import { ResearchReport } from '../components/ResearchReport';
import { SourcePreview } from '../components/SourcePreview';
import type { ResearchSource, StructuredReport } from '../types/research';
interface Shared { question: string; report: string; structuredReport?: StructuredReport; sources: ResearchSource[] }
export default function SharedReportPage({ token }: { token: string }) {
  const [report, setReport] = useState<Shared | null>(null);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<ResearchSource | null>(null);
  useEffect(() => { const tag = document.createElement('meta'); tag.name = 'robots'; tag.content = 'noindex, nofollow'; document.head.appendChild(tag); return () => tag.remove(); }, []);
  useEffect(() => { const controller = new AbortController(); const base = (import.meta.env.DEV ? '' : import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, ''); fetch(`${base}/api/public/reports/${encodeURIComponent(token)}`, { signal: controller.signal, cache: 'no-store' }).then(async response => { const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Shared report unavailable.'); setReport(data); }).catch(error => { if (!controller.signal.aborted) setError(error.message); }); return () => controller.abort(); }, [token]);
  return <main className="mx-auto max-w-6xl p-4 sm:p-8"><p className="mb-6 text-sm text-muted-foreground no-print">FindingsAI · Read-only shared snapshot · <a href="/" className="text-link underline">Open FindingsAI</a></p>{error ? <p role="alert">{error}</p> : report ? <ResearchReport markdown={report.report} structured={report.structuredReport} sources={report.sources} onPreview={setPreview} /> : <p role="status">Loading shared report…</p>}{preview && <SourcePreview source={preview} evidence={[]} onClose={() => setPreview(null)} />}</main>;
}
